import unittest
from gee_batch import ranges, select_batches, task_index

class BatchTests(unittest.TestCase):
    def test_150k_partition_without_loss(self):
        batches = ranges(150000, 1000)
        self.assertEqual(len(batches), 150)
        self.assertEqual(sum(n for _, n in batches), 150000)
        self.assertEqual(ranges(1001, 1000), [(0, 1000), (1000, 1)])
        with self.assertRaises(ValueError):
            ranges(150001, 1000)

    def test_queue_guard_and_resume(self):
        spec = {'batches': [{'description': str(i)} for i in range(30)]}
        tasks = [{'description': str(i), 'state': 'READY'} for i in range(19)]
        self.assertEqual(select_batches(spec, tasks, 10), [{'description': '19'}])
        tasks.append({'description': '19', 'state': 'RUNNING'})
        self.assertEqual(select_batches(spec, tasks, 10), [])

    def test_retry_does_not_resubmit_completed(self):
        spec = {'batches': [{'description': 'a'}, {'description': 'b'}]}
        tasks = [{'description': 'a', 'state': 'COMPLETED'},
                 {'description': 'a', 'state': 'FAILED'},
                 {'description': 'b', 'state': 'FAILED'}]
        self.assertEqual(select_batches(spec, tasks, 5), [])
        self.assertEqual(select_batches(spec, tasks, 5, True), [{'description': 'b'}])
        self.assertEqual(task_index(tasks)['a']['state'], 'COMPLETED')

    def test_current_users_other_jobs_count_toward_guard(self):
        tasks = [{'description': 'other', 'state': 'RUNNING'}]*20
        self.assertEqual(select_batches({'batches':[{'description':'new'}]}, tasks, 5), [])

if __name__ == '__main__':
    unittest.main()
