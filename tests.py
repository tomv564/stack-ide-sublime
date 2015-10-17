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

stackide.Log.verbosity = stackide.Log.VERB_ERROR
cur_dir = os.path.dirname(os.path.realpath(__file__))
stackide.Settings.settings = {"add_to_PATH": []}


def mock_window(paths):
    window = MagicMock()
    window.folders = Mock(return_value=paths)
    window.id = Mock(return_value=1234)
    return window


def mock_view():
    global cur_dir
    view = MagicMock()
    view.file_path = Mock(return_value=cur_dir + '/mocks/helloworld/Setup.hs')
    view.window = Mock(
        return_value=mock_window([cur_dir + '/mocks/helloworld']))
    view.window().active_view = Mock(return_value=view)
    region = MagicMock()
    region.begin = Mock(return_value=1)
    region.end = Mock(return_value=2)
    view.sel = Mock(return_value=[region])
    view.rowcol = Mock(return_value=(0, 0))
    return view


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
        # uses state from prev. test.
        self.assertEqual(1, len(supervisor.window_instances))
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
        instance = stackide.launch_stack_ide(
            mock_window([cur_dir + '/mocks/empty_project']))
        self.assertIsInstance(instance, stackide.NoStackIDE)
        self.assertRegex(instance.reason, "No cabal file found.*")

    def test_launch_window_with_cabal_folder(self):
        cur_dir = os.path.dirname(os.path.realpath(__file__))
        instance = stackide.launch_stack_ide(
            mock_window([cur_dir + '/mocks/cabal_project']))
        self.assertIsInstance(instance, stackide.NoStackIDE)
        self.assertRegex(instance.reason, "No stack.yaml in path.*")

    def test_launch_window_with_wrong_cabal_file(self):
        cur_dir = os.path.dirname(os.path.realpath(__file__))
        instance = stackide.launch_stack_ide(
            mock_window([cur_dir + '/mocks/cabalfile_wrong_project']))
        self.assertIsInstance(instance, stackide.NoStackIDE)
        self.assertRegex(
            instance.reason, "cabalfile_wrong_project.cabal not found.*")

    @unittest.skip("this hangs once stack ide is launched")
    def test_launch_window_with_helloworld_project(self):
        cur_dir = os.path.dirname(os.path.realpath(__file__))
        instance = stackide.launch_stack_ide(
            mock_window([cur_dir + '/mocks/helloworld']))
        self.assertIsInstance(instance, stackide.StackIDE)


class FakeBackend():

    def __init__(self, response=None):
        self.response = response
        self.handler = None

    def send_request(self, req):
        self.response["seq"] = req.get("seq")
        if not self.handler is None:
            self.handler(self.response)


class SelectionTests(unittest.TestCase):

    def test_span_from_view_selection(self):
        cur_dir = os.path.dirname(os.path.realpath(__file__))

        region = MagicMock()
        region.begin = Mock(return_value=1)
        region.end = Mock(return_value=2)
        window = mock_window([cur_dir + '/mocks/helloworld'])

        view = MagicMock()
        view.window = Mock(return_value=window)
        view.sel = Mock(return_value=[region])
        view.file_name = Mock(
            return_value=cur_dir + '/mocks/helloworld/Setup.hs')
        view.rowcol = Mock(return_value=(0, 0))
        span = stackide.span_from_view_selection(view)
        self.assertEqual(1, span['spanFromLine'])
        self.assertEqual(1, span['spanToLine'])
        self.assertEqual(1, span['spanFromColumn'])
        self.assertEqual(1, span['spanToColumn'])
        self.assertEqual('Setup.hs', span['spanFilePath'])


class StackIDETests(unittest.TestCase):

    # @unittest.skip("not done yet")

    def test_can_create(self):
        instance = stackide.StackIDE(
            sublime.FakeWindow('./mocks/helloworld/'), FakeBackend())
        self.assertIsNotNone(instance)
        self.assertTrue(instance.is_active)
        self.assertTrue(instance.is_alive)

    def test_can_send_source_errors_request(self):
        backend = FakeBackend()
        backend.send_request = Mock()
        instance = stackide.StackIDE(
            sublime.FakeWindow('./mocks/helloworld/'), backend)
        self.assertIsNotNone(instance)
        self.assertTrue(instance.is_active)
        self.assertTrue(instance.is_alive)
        req = stackide.StackIDE.Req.get_source_errors()
        instance.send_request(req)
        backend.send_request.assert_called_with(req)

    def test_can_shutdown(self):
        backend = FakeBackend()
        backend.send_request = Mock()
        instance = stackide.StackIDE(
            sublime.FakeWindow('./mocks/helloworld/'), backend)
        self.assertIsNotNone(instance)
        self.assertTrue(instance.is_active)
        self.assertTrue(instance.is_alive)
        instance.end()
        self.assertFalse(instance.is_active)
        self.assertFalse(instance.is_alive)
        backend.send_request.assert_called_with(
            stackide.StackIDE.Req.get_shutdown())
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

    def test_can_clear_panel(self):
        cmd = stackide.ClearErrorPanelCommand()
        cmd.view = MagicMock()
        cmd.run(None)
        cmd.view.erase.assert_called_with(ANY, ANY)

    def test_can_update_panel(self):
        cmd = stackide.UpdateErrorPanelCommand()
        cmd.view = MagicMock()
        cmd.view.size = Mock(return_value=0)
        cmd.run(None, 'message')
        cmd.view.insert.assert_called_with(ANY, 0, "message\n\n")

    def test_can_show_type_at_cursor(self):
        cmd = stackide.ShowHsTypeAtCursorCommand()
        cmd.view = mock_view()
        cmd.view.show_popup = Mock()
        type_info = "YOLO -> Ded"
        span = {
            # "spanFilePath": relative_view_file_name(view),
            "spanFromLine": 1,
            "spanFromColumn": 1,
            "spanToLine": 1,
            "spanToColumn": 5
        }

        response = {"tag": "", "contents": [[type_info, span]]}
        backend = FakeBackend(response)
        instance = stackide.StackIDE(cmd.view.window(), backend)
        backend.handler = instance.handle_response

        stackide.StackIDE.ide_backend_instances[
            cmd.view.window().id()] = instance
        cmd.run(None)
        cmd.view.show_popup.assert_called_with(type_info)

    def test_can_copy_type_at_cursor(self):
        cmd = stackide.CopyHsTypeAtCursorCommand()
        cmd.view = mock_view()
        cmd.view.show_popup = Mock()
        type_info = "YOLO -> Ded"
        span = {
            # "spanFilePath": relative_view_file_name(view),
            "spanFromLine": 1,
            "spanFromColumn": 1,
            "spanToLine": 1,
            "spanToColumn": 5
        }

        response = {"tag": "", "contents": [[type_info, span]]}
        backend = FakeBackend(response)
        instance = stackide.StackIDE(cmd.view.window(), backend)
        backend.handler = instance.handle_response

        stackide.StackIDE.ide_backend_instances[
            cmd.view.window().id()] = instance
        cmd.run(None)
        self.assertEqual(sublime.clipboard, type_info)

    def test_can_request_show_info_at_cursor(self):
        cmd = stackide.ShowHsInfoAtCursorCommand()
        cmd.view = mock_view()
        cmd.view.show_popup = Mock()
        info = {
            "idProp": {
                "idType": "IO ()",
                "idName": "main",
                "idDefSpan": {
                    "contents": {
                        "spanFilePath": "src/Main.hs",
                        "spanFromLine": "5",
                        "spanFromColumn": "3"
                    }
                }
            }
        }
        response = {"tag": "", "contents": [[{"contents" : info}]]}
        backend = FakeBackend(response)
        instance = stackide.StackIDE(cmd.view.window(), backend)
        backend.handler = instance.handle_response

        stackide.StackIDE.ide_backend_instances[cmd.view.window().id()] = instance
        cmd.run(None)
        cmd.view.show_popup.assert_called_with("main :: IO ()  (Defined in src/Main.hs:5:3)")


    def test_show_info_from_module(self):
        cmd = stackide.ShowHsInfoAtCursorCommand()
        cmd.view = mock_view()
        cmd.view.show_popup = Mock()
        info = {
            "idScope": {
                "idImportedFrom": {
                    "moduleName": "Main"
                }
            },
            "idProp": {
                "idType": "IO ()",
                "idName": "main"
            }
        }
        response = {"tag": "", "contents": [[{"contents" : info}]]}
        backend = FakeBackend(response)
        instance = stackide.StackIDE(cmd.view.window(), backend)
        backend.handler = instance.handle_response

        stackide.StackIDE.ide_backend_instances[cmd.view.window().id()] = instance
        cmd.run(None)
        cmd.view.show_popup.assert_called_with("main :: IO ()  (Imported from Main)")

    def test_goto_definition_at_cursor(self):
        global cur_dir
        cmd = stackide.GotoDefinitionAtCursorCommand()
        cmd.view = mock_view()
        cmd.view.show_popup = Mock()
        info = {
            "idProp": {
                "idType": "IO ()",
                "idName": "main",
                "idDefSpan": {
                    "contents": {
                        "spanFilePath": "src/Main.hs",
                        "spanFromLine": "5",
                        "spanFromColumn": "3"
                    }
                }
            }
        }
        response = {"tag": "", "contents": [[{"contents" : info}]]}
        backend = FakeBackend(response)
        window = cmd.view.window()
        window.open_file = Mock()
        instance = stackide.StackIDE(window, backend)
        backend.handler = instance.handle_response

        stackide.StackIDE.ide_backend_instances[cmd.view.window().id()] = instance
        cmd.run(None)
        window.open_file.assert_called_with(cur_dir + "/mocks/helloworld/src/Main.hs:5:3", sublime.ENCODED_POSITION)

    def test_goto_definition_of_module(self):
        global cur_dir
        cmd = stackide.GotoDefinitionAtCursorCommand()
        cmd.view = mock_view()
        cmd.view.show_popup = Mock()
        info = {
            "idScope": {
                "idImportedFrom": {
                    "moduleName": "Main"
                }
            },
            "idProp": {
                "idType": "IO ()",
                "idName": "main"
            }
        }
        # response = {"tag": "", "contents": [[{"contents" : info}]]}
        # backend = FakeBackend(response)
        # window = cmd.view.window()
        # instance = stackide.StackIDE(window, backend)
        # backend.handler = instance.handle_response

        # stackide.StackIDE.ide_backend_instances[cmd.view.window().id()] = instance
        # cmd.run(None)
        window = cmd.view.window()
        window.status_message = Mock()
        cmd._handle_response([[{"contents": info}]])
        # window.status_message.assert_called_with("")
        self.assertEqual("Cannot navigate to main, it is imported from Main", sublime.current_status)


class ListenerTests(unittest.TestCase):

    def test_requests_update_on_save(self):
        listener = stackide.StackIDESaveListener()
        view = mock_view()
        backend = MagicMock()
        window = view.window()
        instance = stackide.StackIDE(window, backend)
        stackide.StackIDE.ide_backend_instances[window.id()] = instance
        backend.send_request = Mock()

        listener.on_post_save(view)

        backend.send_request.assert_any_call(stackide.StackIDE.Req.update_session())
        # backend.send_request.assert_called_with(stackide.StackIDE.Req.get_source_errors())

    def test_type_at_cursor_tests(self):
        listener = stackide.StackIDETypeAtCursorHandler()
        view = mock_view()
        type_info = "YOLO -> Ded"
        span = {
            "spanFilePath": stackide.relative_view_file_name(view),
            "spanFromLine": 1,
            "spanFromColumn": 1,
            "spanToLine": 1,
            "spanToColumn": 5
        }

        response = {"tag": "", "contents": [[type_info, span]]}
        backend = FakeBackend(response)
        instance = stackide.StackIDE(view.window(), backend)
        backend.handler = instance.handle_response
        stackide.StackIDE.ide_backend_instances[
            view.window().id()] = instance

        listener.on_selection_modified(view)
        view.set_status.assert_called_with('type_at_cursor', type_info)
        view.add_regions.assert_called_with('type_at_cursor', ANY, "storage.type", "", sublime.DRAW_OUTLINED)


class HighlightErrorsTests(unittest.TestCase):

    def test_highlight_error(self):
        pass



if __name__ == '__main__':
    unittest.main()