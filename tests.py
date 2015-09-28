import unittest
import os
from unittest.mock import MagicMock, Mock, ANY
plugin = __import__("stack-ide")

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



plugin.Log.verbosity = plugin.Log.VERB_WARNING

def mock_window(paths):
  window = MagicMock()
  window.folders = Mock()
  window.folders.return_value = paths
  return window

class StackIDETests(unittest.TestCase):

  # launching Stack IDE is a function that should result in a
  # Stack IDE instance (null object or live)
  # the null object should contain the reason why the launch failed.

  def test_launch_window_without_folder(self):
    instance = plugin.launch_stack_ide(mock_window([]))
    self.assertIsInstance(instance, plugin.NoStackIDE)
    self.assertRegex(instance.reason, "No folder to monitor.*")

  def test_launch_window_with_empty_folder(self):
    cur_dir = os.path.dirname(os.path.realpath(__file__))
    instance = plugin.launch_stack_ide(mock_window([cur_dir + '/mocks/empty_project']))
    self.assertIsInstance(instance, plugin.NoStackIDE)
    self.assertRegex(instance.reason, "No cabal file found.*")


  def test_launch_window_with_cabal_folder(self):
    cur_dir = os.path.dirname(os.path.realpath(__file__))
    instance = plugin.launch_stack_ide(mock_window([cur_dir + '/mocks/cabal_project']))
    self.assertIsInstance(instance, plugin.NoStackIDE)
    self.assertRegex(instance.reason, "No stack.yaml in path.*")

  def test_launch_window_with_stack_project(self):
    cur_dir = os.path.dirname(os.path.realpath(__file__))
    instance = plugin.launch_stack_ide(mock_window([cur_dir + '/mocks/stack_project']))
    self.assertIsInstance(instance, plugin.StackIDE, instance.reason)


class CommandTests(unittest.TestCase):

  def test_can_clear_view(self):
      cmd = plugin.ClearErrorPanelCommand()
      cmd.view = MagicMock()
      cmd.run(None)
      cmd.view.erase.assert_called_with(ANY, ANY)

class TestStringMethods(unittest.TestCase):

  def test_upper(self):
      self.assertEqual('foo'.upper(), 'FOO')

  def test_isupper(self):
      self.assertTrue('FOO'.isupper())
      self.assertFalse('Foo'.isupper())

  def test_split(self):
      s = 'hello world'
      self.assertEqual(s.split(), ['hello', 'world'])
      # check that s.split fails when the separator is not a string
      with self.assertRaises(TypeError):
          s.split(2)

if __name__ == '__main__':
    unittest.main()
