"""CPU-only decision fixtures, never model samples or GPU launch permission."""
import copy
import importlib.util
from pathlib import Path
import unittest

p=Path(__file__).with_name('check_confirmation_budget.py')
spec=importlib.util.spec_from_file_location('gate',p)
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)


def fixture(k=2):
    names=['a075_b100','a125_b100','a150_b100'][:k]
    count=624+(k+2)*48
    audit={'status':'partial','errors':[],'plan_sha256':gate.PLAN_SHA,'confirm_results_opened':False,
           'locked_operation_ids_not_read':[],'completed_receipts_verified':count,
           'started_receipts_verified':0,'attempt_files_present':count,
           'last_recorded_NFE_per_execution':{'before':171*50,'after':(count-171)*50},
           'stages':{'search':{'status':'complete','selection_verified':True,'completed_images':624,
                               'selection':{'selected':names,'reason':'eligible_candidates'}},
                     'dev':{'status':'complete','selection_verified':True,'completed_images':(k+2)*48,
                            'selection':{'selected':names[:1],'reason':'improvement',
                                         'coefficients':{names[0]:[.75,1]}}}}}
    failed={'failed_attempts':1,'failed_branch_NFE_upper_bound':50,
            'global_attempt_cap_conservative':1440,'global_branch_NFE_cap':72000}
    return audit,failed


class Checks(unittest.TestCase):
    def test_one_promotion_budget(self):
        a,f=fixture(1);r=gate.decide(a,f)
        self.assertEqual(r['status'],'snapshot_ready_for_live_start_checks')
        self.assertEqual((r['final_attempts_with_failure'],r['final_generation_branch_NFE_upper_bound']),(1345,67250))
        self.assertFalse(r['GPU_start_authorized'])
    def test_two_promotion_budget(self):
        a,f=fixture(2);r=gate.decide(a,f)
        self.assertEqual((r['final_attempts_with_failure'],r['final_generation_branch_NFE_upper_bound']),(1393,69650))
    def test_three_promotions_over_budget(self):
        a,f=fixture(3);r=gate.decide(a,f)
        self.assertEqual(r['status'],'budget_exception_required_before_confirmation')
        self.assertEqual((r['excess_attempts'],r['excess_NFE']),(1,50))
    def test_live_process_prevents_overlap(self):
        a,f=fixture();self.assertEqual(gate.decide(a,f,live_process_exists=True)['status'],'wait_for_current_process_exit')
    def test_partial_search_does_not_unlock(self):
        a,f=fixture();a['stages']={'search':{'status':'partial','selection_verified':False}}
        self.assertEqual(gate.decide(a,f)['status'],'wait_for_search_completion')
    def test_search_no_candidate_stops(self):
        a,f=fixture();a['stages']['search']['selection']['selected']=[]
        self.assertEqual(gate.decide(a,f)['status'],'stop_no_qualified_candidate')
    def test_dev_no_gain_stops(self):
        a,f=fixture();a['stages']['dev']['selection']['selected']=[]
        self.assertEqual(gate.decide(a,f)['status'],'stop_no_qualified_candidate')
    def test_started_operation_at_boundary_is_not_replayed(self):
        a,f=fixture();a['started_receipts_verified']=1;a['attempt_files_present']+=1
        with self.assertRaisesRegex(ValueError,'incomplete'):gate.decide(a,f)
    def test_unread_operation_blocks(self):
        a,f=fixture();a['locked_operation_ids_not_read']=['unknown']
        with self.assertRaisesRegex(ValueError,'Unaccounted'):gate.decide(a,f)
    def test_no_confirmation_reentry(self):
        a,f=fixture()
        with self.assertRaisesRegex(ValueError,'already opened'):gate.decide(a,f,already_opened=True)
    def test_failed_attempt_cannot_be_omitted(self):
        a,f=fixture();f['failed_attempts']=0
        with self.assertRaisesRegex(ValueError,'provenance'):gate.decide(a,f)
    def test_extra_NFE_blocks(self):
        a,f=fixture();a['last_recorded_NFE_per_execution']['after']+=50
        with self.assertRaisesRegex(ValueError,'Recorded'):gate.decide(a,f)
    def test_wrong_winner_lineage_blocks(self):
        a,f=fixture();a['stages']['dev']['selection']['selected']=['different']
        with self.assertRaisesRegex(ValueError,'lineage'):gate.decide(a,f)
    def test_failed_independent_audit_blocks(self):
        a,f=fixture();a['errors']=['mismatched summary']
        with self.assertRaisesRegex(ValueError,'audit failed'):gate.decide(a,f)

if __name__=='__main__':unittest.main()
