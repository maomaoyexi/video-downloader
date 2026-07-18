import threading
import unittest

from video_downloader.services.download_manager import DownloadManager


class FakeProcess:
    pass


class DownloadManagerTests(unittest.TestCase):
    def test_begin_and_finish(self):
        manager = DownloadManager()
        handle = manager.begin("single")
        self.assertIsNotNone(handle)
        self.assertIsNone(manager.begin("batch"))
        self.assertTrue(manager.finish(handle))
        self.assertEqual(manager.snapshot()["phase"], "idle")

    def test_stop_before_process_publish(self):
        manager = DownloadManager()
        handle = manager.begin("single")
        ticket = manager.request_stop()
        self.assertTrue(ticket.active)
        self.assertIsNone(ticket.process)
        self.assertTrue(handle.cancel_event.is_set())
        self.assertFalse(manager.publish_process(handle, FakeProcess()))
        self.assertIsNone(manager.begin("batch"))
        self.assertTrue(manager.finish(handle))

    def test_stop_after_process_publish(self):
        manager = DownloadManager()
        handle = manager.begin("single")
        process = FakeProcess()
        self.assertTrue(manager.publish_process(handle, process))
        ticket = manager.request_stop()
        self.assertIs(ticket.process, process)
        self.assertEqual(manager.snapshot()["phase"], "stopping")
        self.assertTrue(manager.clear_process(handle, process))
        self.assertTrue(manager.finish(handle))

    def test_repeated_stop_returns_same_generation(self):
        manager = DownloadManager()
        handle = manager.begin("single")
        first = manager.request_stop()
        second = manager.request_stop()
        self.assertTrue(first.active)
        self.assertTrue(second.active)
        self.assertEqual(first.generation, handle.generation)
        self.assertEqual(second.generation, handle.generation)

    def test_stale_handle_cannot_clear_current_process(self):
        manager = DownloadManager()
        old_handle = manager.begin("single")
        old_process = FakeProcess()
        self.assertTrue(manager.publish_process(old_handle, old_process))
        self.assertTrue(manager.finish(old_handle))
        current_handle = manager.begin("batch")
        current_process = FakeProcess()
        self.assertTrue(manager.publish_process(current_handle, current_process))
        self.assertFalse(manager.clear_process(old_handle, old_process))
        self.assertIs(manager.snapshot()["process"], current_process)

    def test_suspend_blocks_new_tasks_until_resume(self):
        manager = DownloadManager()
        self.assertTrue(manager.suspend())
        self.assertIsNone(manager.begin("single"))
        self.assertEqual(manager.snapshot()["phase"], "suspended")
        manager.resume()
        self.assertIsNotNone(manager.begin("single"))

    def test_concurrent_begin_has_single_winner(self):
        manager = DownloadManager()
        barrier = threading.Barrier(8)
        results = []
        results_lock = threading.Lock()

        def begin():
            barrier.wait()
            handle = manager.begin("single")
            with results_lock:
                results.append(handle)

        threads = [threading.Thread(target=begin) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(sum(handle is not None for handle in results), 1)


if __name__ == "__main__":
    unittest.main()
