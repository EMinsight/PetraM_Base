import traceback
import numpy as np
from scipy.sparse import csr_matrix, coo_matrix, lil_matrix

from petram.model import Pair, Bdry
from petram.phys.phys_model  import Phys

import petram.debug as debug
dprint1, dprint2, dprint3 = debug.init_dprints('EM3D_Floquet')

from petram.mfem_config import use_parallel

if use_parallel:
   from mfem.common.parcsr_extra import ToHypreParCSR, get_row_partitioning
   import mfem.par as mfem
   from mpi4py import MPI
   num_proc = MPI.COMM_WORLD.size
   myid     = MPI.COMM_WORLD.rank
   from mfem.common.mpi_debug import nicePrint
else:
   import mfem.ser as mfem
   num_proc = 1
   myid = 0

'''
   Map DoF from src surface (s1) to dst surface (s2)
   
   s1 and s2 should be plain.

   axis of rotation from s1 to s2 should be perpdicular to
   normal vectors of s1 and s2.

   Twist is not considered?

   For a fineite (non 0, non 180) complex phase difference
   compulex conjugate is returned, to force Lagrange multiplier
   real
'''
def make_mapper(txt, g, indvars):
    lns = {}
    tt = ['    '+indvars[j]+'=xyz['+str(j)+']' for j in range(len(indvars))]
    trans1= ['def trans1(xyz):',
             '    import numpy as np']
    trans1.extend(tt)
    trans1.append('    return np.array(['+txt+'])')
    exec '\n'.join(trans1) in g, lns      # this defines trans1
    mapper  = lns['trans1']
    return mapper
    
def validate_mapper(value, obj, w):
    g = obj._global_ns
    root_phys = obj.get_root_phys()    
    ind_vars = [x.strip() for x in root_phys.ind_vars.split(',')]    
    try:
        make_mapper(value, g, ind_vars)
        return True
    except:
        #traceback.print_exc()
        return False

class WF_PeriodicCommon(Pair, Phys):
    def __init__(self,  **kwargs):
        super(WF_PeriodicCommon, self).__init__(**kwargs)
        Phys.__init__(self)
        
    def attribute_set(self, v):
        v['dstmap_txt'] = "x, y"
        v['srcmap_txt'] = ""
        v['tol_txt'] = "1e-4"
        v['weight_txt']= "1"
        v['tol'] = 1e-4
        v['map_mode'] = "surface"
        super(WF_PeriodicCommon, self).attribute_set(v)
        return v
        
    def panel1_param(self):
        return [['dst mapping ',  self.dstmap_txt, 0, {'validator': validate_mapper,
                                                        'validator_param':self}],
                ['src mapping ',  self.srcmap_txt, 0,  {'validator': validate_mapper,
                                                        'validator_param':self}],
                self.make_phys_param_panel('weight',  self.weight_txt),                
                self.make_phys_param_panel('tol.',  self.tol_txt),
                ["", "u_dst = u_src" ,2, None],]     
#                ["use Lagrange multiplier",   self.use_multiplier,  3, {"text":""}],]     

    def get_panel1_value(self):
        txt = ", ".join([x+"_dst = "+x+"_src" for x in self.get_root_phys().dep_vars])
        return (self.dstmap_txt, self.srcmap_txt, self.weight_txt,
                self.tol_txt, txt)

    def import_panel1_value(self, v):
        self.dstmap_txt = str(v[0])
        self.srcmap_txt = str(v[1])
        self.weight_txt  = str(v[2])        
        self.tol_txt  = str(v[3])

    def make_mapper(self):
        g = self._global_ns
        root_phys = self.get_root_phys()    
        ind_vars = [x.strip() for x in root_phys.ind_vars.split(',')]
        
        dst_mapper = make_mapper(self.dstmap_txt, g, ind_vars)
        if self.srcmap_txt != '':
            src_mapper = make_mapper(self.srcmap_txt, g, ind_vars)
        else:
            src_mapper = dst_mapper
        return dst_mapper, src_mapper

    def eval_wtol(self):
        g = self._global_ns        
        weight = eval(self.weight_txt, g, {})
        tol = eval(self.tol_txt, g, {})
        return weight, tol
    
    def preprocess_params(self, engine):
        ### find normal (outward) vector...
        try:
            dst_mapper, src_mapper = self.make_mapper()
        except:
            import traceback
            traceback.print_exc()
            raise ValueError("Cannot complie mappling rule")

        try:
            weight, tol = self.eval_wtol()
        except:
            import traceback
            traceback.print_exc()
            raise ValueError("Cannot evaluate dphase/tolerance to float number")

    def has_extra_DoF(self, kfes = 0):
        return False

    def has_interpolation_contribution(self, kfes = 0):
        return True

    def add_interpolation_contribution(self, engine, ess_tdof=None, kfes = 0):
        dprint1("Add interpolation contribution(real)" + str(self._sel_index))
        dprint1("kfes = ", str(kfes))

        weight, tol = self.eval_wtol()        
        dprint1("weight = ", str(weight))
        dprint1("tol = ", str(tol))                

        dst_mapper, src_mapper = self.make_mapper()

        tdof = [] if ess_tdof is None else ess_tdof
        src = self._src_index
        dst = [x for x in self._sel_index if not x in self._src_index]

        fes = engine.get_fes(self.get_root_phys(), kfes)
        
        if fes.GetMesh().Dimension() == 3:
            mode =  'surface'
        elif fes.GetMesh().Dimension() == 2:
            mode =  'edge'
        elif fes.GetMesh().Dimension() == 1:
            mode =  'point'
        else:
            assert False, "Unknown coupling mode"
        #old version
        '''
        from petram.helper.dof_mapping_matrix import dof_mapping_matrix
        M, r, c = dof_mapping_matrix(src,  dst,  fes, ess_tdof, 
                                     engine, self.dphase,
                                     map_to_u = map_to_u, map_to_v = map_to_v,
                                     smap_to_u = map_to_u, smap_to_v = map_to_v,
                                     tol = self.tol)
        #nicePrint(M.GetRowPartArray())
        #nicePrint(M.GetColPartArray())
        #nicePrint(M.shape)
        '''
        from petram.helper.dof_map import projection_matrix
        M, r, c = projection_matrix(src, dst, fes, ess_tdof, fes2=fes,
                                    trans1 = dst_mapper, trans2=src_mapper,
                                    dphase = weight,
                                    tol = self.tol, mode = mode)
        return M, r, c
        
class WF_PeriodicBdr(WF_PeriodicCommon, Bdry):
    def __init__(self,  **kwargs):
        super(WF_PeriodicBdr, self).__init__(**kwargs)
        Bdry.__init__(self)
    


