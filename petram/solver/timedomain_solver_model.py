import os
import numpy as np

from petram.model import Model
from .solver_model import Solver

import petram.debug as debug

dprint1, dprint2, dprint3 = debug.init_dprints("TimeDomainSolver")
rprint = debug.regular_print('StdSolver')

class TimeDomain(Solver):
    can_delete = True
    has_2nd_panel = False

    def attribute_set(self, v):
        v['st_et_nt'] = [0, 1, 0.1]
        v['time_step'] = 0.01        
        super(TimeDomain, self).attribute_set(v)
        return v
    
    def panel1_param(self):
        return [["Initial value setting",   self.init_setting,  0, {},],
                ["physics model",   self.phys_model,  0, {},],
                ["start/end/delta time ",  "",  0, {},],
                ["time step",   "",  0, {},],
                ["probes",   self.probe,  0, {},],                
                ["clear working directory",
                 self.clear_wdir,  3, {"text":""}],
                ["initialize solution only",
                 self.init_only,  3, {"text":""}], 
                ["convert to real matrix (complex prob.)",
                 self.assemble_real,  3, {"text":""}],
                ["save parallel mesh",
                 self.save_parmesh,  3, {"text":""}],
                ["use cProfiler",
                 self.use_profiler,  3, {"text":""}],]

    def get_panel1_value(self):
        st_et_nt = ", ".join([str(x) for x in self.st_et_nt])
        return (self.init_setting,
                self.phys_model,
                st_et_nt,
                str(self.time_step),
                self.probe,                
                self.clear_wdir,
                self.init_only,               
                self.assemble_real,
                self.save_parmesh,
                self.use_profiler)        
    
    def import_panel1_value(self, v):
        self.init_setting = str(v[0])        
        self.phys_model = str(v[1])
        tmp = str(v[2]).split(',')
        st_et_nt = [tmp[0], tmp[1], ",".join(tmp[2:])]
        self.st_et_nt = [eval(x) for x in st_et_nt]
        self.time_step= float(v[3])
        self.probe = str(v[4])
        self.clear_wdir = v[5]
        self.init_only = v[7]        
        self.assemble_real = v[7]
        self.save_parmesh = v[8]
        self.use_profiler = v[9]                

    def get_possible_child(self):
        choice = []
        try:
            from petram.solver.mumps_model import MUMPS
            choice.append(MUMPS)
        except ImportError:
            pass

        try:
            from petram.solver.gmres_model import GMRES
            choice.append(GMRES)
        except ImportError:
            pass

        try:
            from petram.solver.strumpack_model import SpSparse
            choice.append(SpSparse)
        except ImportError:
            pass
        return choice
    '''
    def init_sol(self, engine):
        phys_target = self.get_phys()
        num_matrix= engine.run_set_matrix_weight(phys_target, self)
        
        engine.set_formblocks(phys_target, num_matrix)
        
        for p in phys_target:
            engine.run_mesh_extension(p)
            
        engine.run_alloc_sol(phys_target)
        
        inits = self.get_init_setting()
        if len(inits) == 0:
            # in this case alloate all fespace and initialize all
            # to zero
            engine.run_apply_init(phys_target, 0)
        else:
            for init in inits:
                init.run(engine)
        engine.run_apply_essential(phys_target)
        return 

    def get_matrix_weight(self, timestep_config, timestep_weight):
        dt = float(self.time_step)
        lns = self.root()['General']._global_ns.copy()
        lns['dt'] = dt

        wt = [eval(x, lns) for x in timestep_weight]
        return wt
    
    def compute_A_rhs(self, M, B, X):
        #M/dt u_1 + K u_1 = M/dt u_0 + b
        print "M, B, X", M, B, X
        one_dt = 1/float(self.time_step)
        MM = M[1]*one_dt
        RHS = MM.dot(X[1]) + B
        A = M[0]+ M[1]*one_dt
        self.M = M
        return A, RHS
    
    def compute_rhs(self, B, sol, dt):
        one_dt = 1/float(dt)
        MM = self.M[1]*one_dt
        RHS = MM.dot(sol) + B
        return RHS

    def assemble(self, engine):
        phys_target = self.get_phys()
        engine.run_verify_setting(phys_target, self)
        engine.run_assemble_mat(phys_target)
        engine.run_assemble_rhs(phys_target)
        blocks = engine.run_assemble_blocks(self)
        A, X, RHS, Ae, B = blocks

        return blocks # A, X, RHS, Ae, B

    def store_rhs(self, engine):
        phys_target = self.get_phys()
        vecs, vecs_c = engine.run_assemble_rhs(phys_target)
        blocks = engine.generate_rhs(phys_targets, vecs, vecs_c)
        self.B.append(blocks[1])

    def call_solver(self, engine, blocks):
        A, X, RHS, Ae, B = blocks
        
        solver = self.get_active_solver()        
        phys_target = self.get_phys()        
        phys_real = all([not p.is_complex() for p in phys_target])
        ls_type = solver.linear_system_type(self.assemble_real,
                                            phys_real)
        
        #ls_type: coo  (matrix in coo format : DMUMP or ZMUMPS)
        #         coo_real  (matrix in coo format converted from complex 
        #                    matrix : DMUMPS)
        # below is a plan...
        #         blk (matrix made mfem:block operator)
        #         blk_real (matrix made mfem:block operator for complex
        #                     problem)
        #                  (unknowns are in the order of  R_fes1, R_fes2,... I_fes1, Ifes2...)
        #         blk_interleave (unknowns are in the order of  R_fes1, I_fes1, R_fes2, I_fes2,...)
        #         None(not supported)
        #if debug.debug_memory:
        #    dprint1("Block Matrix before shring :\n",  self.M)
        #    dprint1(debug.format_memory_usage())                
        #M_block, B_blocks, P = engine.eliminate_and_shrink(self.M,
        #                                                   self.B, self.Me)
        
        if debug.debug_memory:
            dprint1(debug.format_memory_usage())

        from petram.sol.probe import Probe
        probe_names = [x.strip() for x in self.probe.split(',')]
        probe_idx =  [engine.dep_var_offset(n) for n in probe_names]
        probes = [Probe(n, i) for n, i in zip(probe_names, probe_idx)]
        
        st, et, nt = self.st_et_nt
        dt = self.time_step
        try:
            checkpoint = [x for x in nt]
        except:
            checkpoint = np.linspace(st, et, nt)
        dprint1("checkpoint", checkpoint)        
        icheckpoint = 0
        t = st
        od = os.getcwd()
        
        dprint1("A", A)
        dprint1("RHS", RHS)
        dprint1("time", t)
        AA = engine.finalize_matrix(A, not phys_real, format = ls_type)
        BB = engine.finalize_rhs([RHS], not phys_real, format = ls_type)

        datatype = 'Z' if (AA.dtype == 'complex') else 'D'
        Solver = solver.create_solver_instance(datatype)
        Solver.SetOperator(AA, dist = engine.is_matrix_distributed)

        counter = 0
        while True:
            #solall = solver.solve(engine, AA, BB)
            dprint1("before multi")
            dprint1(debug.format_memory_usage())
            
            solall = Solver.Mult(BB, case_base=engine.case_base)
            engine.case_base += BB.shape[1]
            
            if not phys_real and self.assemble_real:
                solall = solver.real_to_complex(solell, self.A)
            t = t + dt
            counter += 1
            dprint1("TimeStep ("+str(counter)+ "), t="+str(t))
            if t >= et: break
            #if counter > 5: break
            
            dprint1("before reformat")
            dprint1(debug.format_memory_usage())
            
            sol = A.reformat_central_mat(solall, 0)

            dprint1("after reformat")
            dprint1(debug.format_memory_usage())
            for p in probes:
                p.append_sol(sol, t)
                
            if checkpoint[icheckpoint] < t:
                 dprint1("writing checkpoint t=" + str(t) + "("+str(icheckpoint)+")")
                 
                 extra_data = self.store_sol(engine, sol, blocks[1][0], 0)
                 path = os.path.join(od, 'checkpoint_' + str(icheckpoint))
                 engine.mkdir(path) 
                 os.chdir(path)
                 engine.cleancwd() 
                 self.save_solution(engine, extra_data)
                 
                 icheckpoint = icheckpoint+1
            os.chdir(od)
            dprint1("before compute_rhs")                                    
            dprint1(debug.format_memory_usage())                
            
            RHS = self.compute_rhs(B, sol, self.time_step)

            dprint1("before eliminateBC")                                    
            dprint1(debug.format_memory_usage())
            
            RHS = engine.eliminateBC(Ae, X[1], RHS)
            BB = engine.finalize_rhs([RHS], not phys_real, format = ls_type)
            dprint1("end reformat")                                    
            dprint1(debug.format_memory_usage())                

        #PT = P.transpose()
        sol = A.reformat_central_mat(solall, 0)

        for p in probes:
            p.write_file()

        return sol
    '''            
    @debug.use_profiler
    def run(self, engine):
        if self.clear_wdir:
            engine.remove_solfiles()

        instance = FirstOrderBackwardEuler(self, engine)
        
        st, et, nt = self.st_et_nt
        instance.set_start(st)
        instance.set_end(et)
        instance.set_checkpoint(np.linspace(st, et, nt))
        instance.set_timestep(self.time_step)

        instance.configure_probes(self.probe)

        finished = instance.init(self.init_only)
        while not finished:
            finished = instance.step()

        instance.save_solution(ksol = 0,
                               skip_mesh = False, 
                               mesh_only = False,
                               save_parmesh=self.save_parmesh)
        
        print(debug.format_memory_usage())


from petram.solver.solver_model import TimeDependentSolverInstance

class FirstOrderBackwardEuler(TimeDependentSolverInstance):
    '''
    Fixed time step solver
    '''
    def __init__(self, gui, engine):
        TimeDependentSolverInstance.__init__(self, gui, engine)
        self.pre_assembled = False
        self.assembled = False
        self.counter = 0
        self.icheckpoint = 0

    def init(self, init_only=False):
        self.time = self.st
        if self.time == self.et: return True

        self.counter = 0
        self.icheckpoint = 0
        engine = self.engine
                      
        phys_target = self.get_phys()
        num_matrix= engine.run_set_matrix_weight(phys_target, self.get_matrix_weight)
        
        engine.set_formblocks(phys_target, num_matrix)
        
        for p in phys_target:
            engine.run_mesh_extension(p)
            
        engine.run_alloc_sol(phys_target)
        
        inits = self.get_init_setting()
        if len(inits) == 0:
            # in this case alloate all fespace and initialize all
            # to zero
            engine.run_apply_init(phys_target, 0)
        else:
            for init in inits:
                init.run(engine)
        engine.run_apply_essential(phys_target)
        
        self.pre_assemble()
        self.assemble()
        A, X, RHS, Ae, B, M = self.blocks        
        self.sol = X[0]
        
        if init_only:
            self.write_checkpoint_solution()
            return True
        else:
            return False
                      
    def get_matrix_weight(self, timestep_config, timestep_weight):
        dt = float(self.time_step)
        lns = self.engine.model['General']._global_ns.copy()
        lns['dt'] = dt

        wt = [eval(x, lns) for x in timestep_weight]
        return wt

    def pre_assemble(self):
        engine = self.engine
        phys_target = self.get_phys()
        engine.run_verify_setting(phys_target, self.gui)
        engine.run_assemble_mat(phys_target)
        engine.run_assemble_rhs(phys_target)
        self.pre_assembled = True


    def compute_A(self, M, B, X):
        '''
        M/dt u_1 + K u_1 = M/dt u_0 + b
        '''
        print "M, B, X", M, B, X
        one_dt = 1/float(self.time_step)
        MM = M[1]*one_dt
        A = M[0]+ M[1]*one_dt
        self.M = M
        return A
    
    def compute_rhs(self, M, B, X):
        one_dt = 1/float(self.time_step)
        MM = M[1]*one_dt
        RHS = MM.dot(X[-1]) + B
        return RHS
        
    def assemble(self):
        self.blocks = self.engine.run_assemble_blocks(self.compute_A, self.compute_rhs)
        #A, X, RHS, Ae, B, M = blocks
        self.assembled = True
        
    def step(self):
        engine = self.engine

        if not self.pre_assembled:
            assert False, "pre_assmeble must have been called"
            
        if self.counter == 0:
            A, X, RHS, Ae, B, M = self.blocks        
            AA = engine.finalize_matrix(A, not self.phys_real, format = self.ls_type)
            BB = engine.finalize_rhs([RHS], not self.phys_real, format = self.ls_type)
            self.write_checkpoint_solution()
            self.icheckpoint += 1
        else:
            A, X, RHS, Ae, B, M = self.blocks                    
            RHS = self.compute_rhs(M, B, [self.sol])
            dprint1("before eliminateBC")                                    
            dprint1(debug.format_memory_usage())
            RHS = engine.eliminateBC(Ae, X[1], RHS)
            BB = engine.finalize_rhs([RHS], not self.phys_real, format = self.ls_type)

        if self.linearsolver is None:
            if self.ls_type.startswith('coo'):
                datatype = 'Z' if (AA.dtype == 'complex') else 'D'
            else:
                datatype = 'D'
            self.linearsolver  = self.linearsolver_model.allocate_solver(datatype)
            self.linearsolver.SetOperator(AA, dist = engine.is_matrix_distributed)

        solall = self.linearsolver.Mult(BB, case_base=engine.case_base)
        engine.case_base += BB.shape[1]
            
        if not self.phys_real and self.assemble_real:
            assert False, "this has to be debugged (convertion from real to complex)"
            solall = self.linearsolver_model.real_to_complex(solell, A)
            
        self.time = self.time + self.time_step
        self.counter += 1
        
        self.sol = A.reformat_central_mat(solall, 0)

        for p in self.probe:
            p.append_sol(sol, t)
                
        if self.checkpoint[self.icheckpoint] < self.time:
            self.write_checkpoint_solution()
            self.icheckpoint += 1
            
        return self.time >= self.et

    def write_checkpoint_solution(self):
        dprint1("writing checkpoint t=" + str(self.time) +
                "("+str(self.icheckpoint)+")")        
        od = os.getcwd()
        path = os.path.join(od, 'checkpoint_' + str(self.icheckpoint))
        self.engine.mkdir(path) 
        os.chdir(path)
        self.engine.cleancwd() 
        self.save_solution()
        os.chdir(od)        

                      
                      


