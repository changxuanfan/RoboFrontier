import unittest
from robofrontier.oracle.run_relay_live_oracle import total_stop_requested


class RelayOwnerStopTests(unittest.TestCase):
    def test_terminal_stop_and_commission_boundary_never_enter_recovery(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from robofrontier.oracle.run_relay_live_oracle import attempt_with_recovery, CommissionComplete
        from robofrontier.oracle.trial import ReferenceStopped
        trial=SimpleNamespace(monitor=SimpleNamespace(violations=[]))
        for error in (ReferenceStopped('owner stop'),KeyboardInterrupt(),CommissionComplete()):
            with self.subTest(kind=type(error).__name__):
                recovery=Mock()
                operation=Mock(side_effect=error)
                with self.assertRaises(type(error)):
                    attempt_with_recovery(trial,operation,recovery)
                operation.assert_called_once_with()
                recovery.wait_for_repair.assert_not_called()

    def test_ordinary_recoverable_fault_keeps_native_repair_but_violation_does_not(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from robofrontier.oracle.run_relay_live_oracle import attempt_with_recovery
        trial=SimpleNamespace(monitor=SimpleNamespace(violations=[]))
        error=RuntimeError('grasp needs forward repair')
        operation=Mock(side_effect=error)
        recovery=Mock()
        recovery.wait_for_repair.return_value='resume'
        self.assertEqual(attempt_with_recovery(trial,operation,recovery),'resume')
        recovery.wait_for_repair.assert_called_once_with(error)
        trial.monitor.violations=['collision']
        recovery.reset_mock()
        with self.assertRaises(RuntimeError):
            attempt_with_recovery(trial,operation,recovery)
        recovery.wait_for_repair.assert_not_called()

class RelayTotalDeadlineTests(unittest.TestCase):
    def test_normal_run_has_no_elapsed_time_deadline(self):
        self.assertFalse(total_stop_requested(10**9,0))
    def test_explicit_operator_stop_remains_available(self):
        self.assertTrue(total_stop_requested(1,0,True))
    def test_only_an_explicit_positive_limit_enables_a_deadline(self):
        self.assertFalse(total_stop_requested(10,20))
        self.assertTrue(total_stop_requested(21,20))

if __name__=='__main__':unittest.main()
