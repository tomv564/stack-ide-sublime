import unittest
import os
from unittest.mock import MagicMock, Mock, ANY
import stackide
from mocks import sublime

# on os-x:
# sudo pip install magicmock==1.0.1

# Untested

# Watchdog hooks.
# plugin_loaded
# plugin_unloaded

# start up is deferred to static methods on StackIDE
# .. why not just put that functionality in the Watchdog itself
# and leave the StackIDE instances to manage single processes?
# TODO: move check_windows to Watchdog class.

# StackIDE lifecycle:
#

# Issues ran into:
# Cannot detect if the first request is made
# Calls to settings everywhere, can this not be loaded in the watchdog and
# be passed in to all instances? We can then avoid using the static log methods
# everywhere too.

# stackide.Log.verbosity = stackide.Log.VERB_WARNING
stackide.Settings.settings = {"add_to_PATH": []}


def mock_window(paths):
  window = MagicMock()
  window.folders = Mock()
  window.folders.return_value = paths
  return window


class SupervisorTests(unittest.TestCase):

  def test_can_create(self):
    supervisor = stackide.Supervisor()
    self.assertIsNotNone(supervisor)
    self.assertEqual(0, len(supervisor.window_instances))

  def test_creates_initial_window(self):
    sublime.create_window('.')
    supervisor = stackide.Supervisor()
    self.assertEqual(1, len(supervisor.window_instances))

  def test_monitors_closed_windows(self):
    supervisor = stackide.Supervisor()
    self.assertEqual(1, len(supervisor.window_instances)) #uses state from prev. test.
    sublime.destroy_windows()
    supervisor.check_instances()
    self.assertEqual(0, len(supervisor.window_instances))

  def test_monitors_new_windows(self):
    supervisor = stackide.Supervisor()
    self.assertEqual(0, len(supervisor.window_instances))
    sublime.create_window('.')
    supervisor.check_instances()
    self.assertEqual(1, len(supervisor.window_instances))


class LaunchTests(unittest.TestCase):

  # launching Stack IDE is a function that should result in a
  # Stack IDE instance (null object or live)
  # the null object should contain the reason why the launch failed.

  def test_launch_window_without_folder(self):
    instance = stackide.launch_stack_ide(mock_window([]))
    self.assertIsInstance(instance, stackide.NoStackIDE)
    self.assertRegex(instance.reason, "No folder to monitor.*")

  def test_launch_window_with_empty_folder(self):
    cur_dir = os.path.dirname(os.path.realpath(__file__))
    instance = stackide.launch_stack_ide(mock_window([cur_dir + '/mocks/empty_project']))
    self.assertIsInstance(instance, stackide.NoStackIDE)
    self.assertRegex(instance.reason, "No cabal file found.*")

  def test_launch_window_with_cabal_folder(self):
    cur_dir = os.path.dirname(os.path.realpath(__file__))
    instance = stackide.launch_stack_ide(mock_window([cur_dir + '/mocks/cabal_project']))
    self.assertIsInstance(instance, stackide.NoStackIDE)
    self.assertRegex(instance.reason, "No stack.yaml in path.*")

  @unittest.skip("this hangs once stack ide is launched")
  def test_launch_window_with_helloworld_project(self):
    cur_dir = os.path.dirname(os.path.realpath(__file__))
    instance = stackide.launch_stack_ide(mock_window([cur_dir + '/mocks/helloworld']))
    self.assertIsInstance(instance, stackide.StackIDE)



class FakeProcess():

  def __init__(self):
    pass




class StackIDETests(unittest.TestCase):

  # @unittest.skip("not done yet")
  def test_can_create(self):
      instance = stackide.StackIDE(sublime.FakeWindow('./mocks/helloworld/'), FakeProcess())
      self.assertIsNotNone(instance)
      self.assertTrue(instance.is_active)
      self.assertTrue(instance.is_alive)


  def test_can_send_source_errors_request(self):
      process = FakeProcess()
      process.send_request = Mock()
      instance = stackide.StackIDE(sublime.FakeWindow('./mocks/helloworld/'), process)
      self.assertIsNotNone(instance)
      self.assertTrue(instance.is_active)
      self.assertTrue(instance.is_alive)
      req = stackide.StackIDE.Req.get_source_errors
      instance.send_request(req)
      process.send_request.assert_called_with(req)

  def test_can_shutdown(self):
      process = FakeProcess()
      process.send_request = Mock()
      instance = stackide.StackIDE(sublime.FakeWindow('./mocks/helloworld/'), process)
      self.assertIsNotNone(instance)
      self.assertTrue(instance.is_active)
      self.assertTrue(instance.is_alive)
      instance.end()
      self.assertFalse(instance.is_active)
      self.assertFalse(instance.is_alive)
      process.send_request.assert_called_with(stackide.StackIDE.Req.get_shutdown())
      # self.assertEqual(1, len(process.send_request.mock_calls))


class UtilTests(unittest.TestCase):

  def test_get_relative_filename(self):

      cur_dir = os.path.dirname(os.path.realpath(__file__))
      window = mock_window([cur_dir + '/mocks/helloworld'])

      view = MagicMock()
      view.window = Mock()
      view.window.return_value = window
      view.file_name = Mock()
      view.file_name.return_value = cur_dir + '/mocks/helloworld/Setup.hs'
      # calls view.window() , first_folder calls window.folders()
      # calls view.file_name()
      self.assertEqual('Setup.hs', stackide.relative_view_file_name(view))

class CommandTests(unittest.TestCase):

  def test_can_clear_view(self):
      cmd = stackide.ClearErrorPanelCommand()
      cmd.view = MagicMock()
      cmd.run(None)
      cmd.view.erase.assert_called_with(ANY, ANY)

if __name__ == '__main__':
    unittest.main()
