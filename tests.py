import unittest
from mock import MagicMock, ANY
plugin = __import__("stack-ide")

# on os-x:
# sudo pip install magicmock==1.0.1

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
