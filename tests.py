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

# TEST DATA

source_errors = {'seq': 'd0599c00-0b77-441c-8947-b3882cab298c', 'tag': 'ResponseGetSourceErrors', 'contents': [{'errorSpan': {'tag': 'ProperSpan', 'contents': {'spanFromColumn': 22, 'spanFromLine': 11, 'spanFilePath': 'src/Lib.hs', 'spanToColumn': 28, 'spanToLine': 11}}, 'errorKind': 'KindError', 'errorMsg': 'Couldn\'t match expected type ‘Integer’ with actual type ‘[Char]’\nIn the first argument of ‘greet’, namely ‘"You!"’\nIn the second argument of ‘($)’, namely ‘greet "You!"’\nIn a stmt of a \'do\' block: putStrLn $ greet "You!"'}, {'errorSpan': {'tag': 'ProperSpan', 'contents': {'spanFromColumn': 24, 'spanFromLine': 15, 'spanFilePath': 'src/Lib.hs', 'spanToColumn': 25, 'spanToLine': 15}}, 'errorKind': 'KindError', 'errorMsg': 'Couldn\'t match expected type ‘[Char]’ with actual type ‘Integer’\nIn the second argument of ‘(++)’, namely ‘s’\nIn the expression: "Hello, " ++ s'}]}

someFunc_span_info = {'contents': [[{'contents': {'idProp': {'idDefinedIn': {'moduleName': 'Lib', 'modulePackage': {'packageVersion': None, 'packageName': 'main', 'packageKey': 'main'}}, 'idSpace': 'VarName', 'idType': 'IO ()', 'idDefSpan': {'contents': {'spanFromLine': 9, 'spanFromColumn': 1, 'spanToColumn': 9, 'spanFilePath': 'src/Lib.hs', 'spanToLine': 9}, 'tag': 'ProperSpan'}, 'idName': 'someFunc', 'idHomeModule': None}, 'idScope': {'idImportQual': '', 'idImportedFrom': {'moduleName': 'Lib', 'modulePackage': {'packageVersion': None, 'packageName': 'main', 'packageKey': 'main'}}, 'idImportSpan': {'contents': {'spanFromLine': 3, 'spanFromColumn': 1, 'spanToColumn': 11, 'spanFilePath': 'app/Main.hs', 'spanToLine': 3}, 'tag': 'ProperSpan'}, 'tag': 'Imported'}}, 'tag': 'SpanId'}, {'spanFromLine': 7, 'spanFromColumn': 27, 'spanToColumn': 35, 'spanFilePath': 'app/Main.hs', 'spanToLine': 7}]], 'seq': '724752c9-a7bf-4658-834a-3ff7df64e7e5', 'tag': 'ResponseGetSpanInfo'}
putStrLn_span_info = {'contents': [[{'contents': {'idProp': {'idDefinedIn': {'moduleName': 'System.IO', 'modulePackage': {'packageVersion': '4.8.1.0', 'packageName': 'base', 'packageKey': 'base'}}, 'idSpace': 'VarName', 'idType': 'String -> IO ()', 'idDefSpan': {'contents': '<no location info>', 'tag': 'TextSpan'}, 'idName': 'putStrLn', 'idHomeModule': {'moduleName': 'System.IO', 'modulePackage': {'packageVersion': '4.8.1.0', 'packageName': 'base', 'packageKey': 'base'}}}, 'idScope': {'idImportQual': '', 'idImportedFrom': {'moduleName': 'Prelude', 'modulePackage': {'packageVersion': '4.8.1.0', 'packageName': 'base', 'packageKey': 'base'}}, 'idImportSpan': {'contents': {'spanFromLine': 1, 'spanFromColumn': 8, 'spanToColumn': 12, 'spanFilePath': 'app/Main.hs', 'spanToLine': 1}, 'tag': 'ProperSpan'}, 'tag': 'Imported'}}, 'tag': 'SpanId'}, {'spanFromLine': 7, 'spanFromColumn': 41, 'spanToColumn': 49, 'spanFilePath': 'app/Main.hs', 'spanToLine': 7}]], 'seq': '6ee8d949-82bd-491d-8b79-ffcaa3e65fde', 'tag': 'ResponseGetSpanInfo'}
readFile_exp_types = {'tag': 'ResponseGetExpTypes', 'contents': [['FilePath -> IO String', {'spanToColumn': 25, 'spanToLine': 10, 'spanFromColumn': 17, 'spanFromLine': 10, 'spanFilePath': 'src/Lib.hs'}], ['IO String', {'spanToColumn': 36, 'spanToLine': 10, 'spanFromColumn': 17, 'spanFromLine': 10, 'spanFilePath': 'src/Lib.hs'}], ['IO ()', {'spanToColumn': 28, 'spanToLine': 11, 'spanFromColumn': 12, 'spanFromLine': 9, 'spanFilePath': 'src/Lib.hs'}]], 'seq': 'fd3eb2a5-e390-4ad7-be72-8b2e82441a95'}

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
    view.file_name = Mock(return_value="Setup.hs")
    window = mock_window([cur_dir + '/mocks/helloworld'])
    window.active_view = Mock(return_value=view)
    window.find_open_file = Mock(return_value=view)
    window.views = Mock(return_value=[view])
    view.window = Mock(return_value=window)
    region = MagicMock()
    region.begin = Mock(return_value=1)
    region.end = Mock(return_value=2)
    view.sel = Mock(return_value=[region])
    view.rowcol = Mock(return_value=(0, 0))
    view.text_point = Mock(return_value=20)
    return view


class ParsingTests(unittest.TestCase):

    def test_parse_source_errors_empty(self):
        errors = stackide.parse_source_errors([])
        self.assertEqual(0, len(list(errors)))

    def test_parse_source_errors_error(self):
        errors = list(stackide.parse_source_errors(source_errors.get('contents')))
        self.assertEqual(2, len(errors))
        err1, err2 = errors
        self.assertEqual(err1.kind, 'KindError')
        self.assertRegex(err1.msg, "Couldn\'t match expected type ‘Integer’")
        self.assertEqual(err1.span.filePath, 'src/Lib.hs')
        self.assertEqual(err1.span.fromLine, 11)
        self.assertEqual(err1.span.fromColumn, 22)

        self.assertEqual(err2.kind, 'KindError')
        self.assertRegex(err2.msg, "Couldn\'t match expected type ‘\[Char\]’")
        self.assertEqual(err2.span.filePath, 'src/Lib.hs')
        self.assertEqual(err2.span.fromLine, 15)
        self.assertEqual(err2.span.fromColumn, 24)

    def test_parse_exp_types_empty(self):
        exp_types = stackide.parse_exp_types([])
        self.assertEqual(0, len(list(exp_types)))

    def test_parse_exp_types_readFile(self):
        exp_types = list(stackide.parse_exp_types(readFile_exp_types.get('contents')))
        self.assertEqual(3, len(exp_types))
        (type, span) = exp_types[0]

        self.assertEqual('FilePath -> IO String', type)
        self.assertEqual('src/Lib.hs', span.filePath)


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

        # response = {"tag": "", "contents": [[{"contents" : someFunc_span_info}, {}]]}
        backend = FakeBackend(someFunc_span_info)
        instance = stackide.StackIDE(cmd.view.window(), backend)
        backend.handler = instance.handle_response

        stackide.StackIDE.ide_backend_instances[cmd.view.window().id()] = instance
        cmd.run(None)
        cmd.view.show_popup.assert_called_with("someFunc :: IO ()  (Defined in src/Lib.hs:9:1)")


    def test_show_info_from_module(self):
        cmd = stackide.ShowHsInfoAtCursorCommand()
        cmd.view = mock_view()
        cmd.view.show_popup = Mock()
        # response = {"tag": "", "contents": [[{"contents" : putStrLn_span_info}, {}]]}
        backend = FakeBackend(putStrLn_span_info)
        instance = stackide.StackIDE(cmd.view.window(), backend)
        backend.handler = instance.handle_response

        stackide.StackIDE.ide_backend_instances[cmd.view.window().id()] = instance
        cmd.run(None)
        cmd.view.show_popup.assert_called_with("putStrLn :: String -> IO ()  (Imported from Prelude)")

    def test_goto_definition_at_cursor(self):
        global cur_dir
        cmd = stackide.GotoDefinitionAtCursorCommand()
        cmd.view = mock_view()
        cmd.view.show_popup = Mock()
        # response = {"tag": "", "contents": [[{"contents": someFunc_span_info}, {}]]}
        backend = FakeBackend(someFunc_span_info)
        window = cmd.view.window()
        window.open_file = Mock()
        instance = stackide.StackIDE(window, backend)
        backend.handler = instance.handle_response

        stackide.StackIDE.ide_backend_instances[cmd.view.window().id()] = instance
        cmd.run(None)
        window.open_file.assert_called_with(cur_dir + "/mocks/helloworld/src/Lib.hs:9:1", sublime.ENCODED_POSITION)

    def test_goto_definition_of_module(self):
        global cur_dir
        cmd = stackide.GotoDefinitionAtCursorCommand()
        cmd.view = mock_view()
        cmd.view.show_popup = Mock()
        window = cmd.view.window()
        window.status_message = Mock()
        cmd._handle_response(putStrLn_span_info.get('contents'))
        self.assertEqual("Cannot navigate to putStrLn, it is imported from Prelude", sublime.current_status)


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
        view.set_status.assert_called_with("type_at_cursor", type_info)
        view.add_regions.assert_called_with("type_at_cursor", ANY, "storage.type", "", sublime.DRAW_OUTLINED)


class WinTests(unittest.TestCase):

    def test_highlight_type_clear(self):
        view = mock_view()
        stackide.Win(view.window()).highlight_type([])
        view.set_status.assert_called_with("type_at_cursor", "")
        view.add_regions.assert_called_with("type_at_cursor", [], "storage.type", "", sublime.DRAW_OUTLINED)

    def test_highlight_no_errors(self):
        view = mock_view()
        window = view.window()
        window.run_command = Mock()
        panel = MagicMock()
        window.create_output_panel = Mock(return_value=panel)
        errors = []
        stackide.Win(window).highlight_errors(errors)
        window.create_output_panel.assert_called_with("hide_errors")

        panel.settings().set.assert_called_with("result_file_regex", "^(..[^:]*):([0-9]+):?([0-9]+)?:? (.*)$")
        window.run_command.assert_any_call("hide_panel",  {"panel": "output.hide_errors"})
        panel.run_command.assert_called_with("clear_error_panel")
        panel.set_read_only.assert_any_call(False)

        view.add_regions.assert_any_call("errors", [], "invalid", "dot", sublime.DRAW_OUTLINED)
        view.add_regions.assert_any_call("warnings", [], "comment", "dot", sublime.DRAW_OUTLINED)

        window.run_command.assert_called_with("hide_panel", {"panel": "output.hide_errors"})
        panel.set_read_only.assert_any_call(True)

    def test_highlight_errors_and_warnings(self):
        view = mock_view()
        window = view.window()
        window.run_command = Mock()
        panel = MagicMock()
        window.create_output_panel = Mock(return_value=panel)
        error = {
            "errorKind": "KindError",
            "errorMsg": "<error message here>",
            "errorSpan": {
                "tag": "ProperSpan",
                "contents": {
                    "spanFilePath": stackide.relative_view_file_name(view),
                    "spanFromLine": 1,
                    "spanFromColumn": 1,
                    "spanToLine": 1,
                    "spanToColumn": 5
                }
            }
        }
        warning = {
            "errorKind": "KindWarning",
            "errorMsg": "<warning message here>",
            "errorSpan": {
                "tag": "ProperSpan",
                "contents": {
                    "spanFilePath": stackide.relative_view_file_name(view),
                    "spanFromLine": 1,
                    "spanFromColumn": 1,
                    "spanToLine": 1,
                    "spanToColumn": 5
                }
            }
        }
        errors = [error, warning]
        stackide.Win(window).highlight_errors(errors)
        window.create_output_panel.assert_called_with("hide_errors")

        panel.settings().set.assert_called_with("result_file_regex", "^(..[^:]*):([0-9]+):?([0-9]+)?:? (.*)$")
        window.run_command.assert_any_call("hide_panel",  {"panel": "output.hide_errors"})
        # panel.run_command.assert_any_call("clear_error_panel")
        panel.set_read_only.assert_any_call(False)

        # panel should have received messages
        panel.run_command.assert_any_call("update_error_panel", {"message": "Setup.hs:1:1: KindError:\n<error message here>"})
        panel.run_command.assert_any_call("update_error_panel", {"message": "Setup.hs:1:1: KindWarning:\n<warning message here>"})

        view.add_regions.assert_called_with("warnings", [ANY], "comment", "dot", sublime.DRAW_OUTLINED)
        view.add_regions.assert_any_call('errors', [ANY], 'invalid', 'dot', 2)
        window.run_command.assert_called_with("show_panel", {"panel": "output.hide_errors"})
        panel.set_read_only.assert_any_call(True)


class AutocompleteTests(unittest.TestCase):

    def test_request_completions(self):
        view = mock_view()
        listener = stackide.StackIDEAutocompleteHandler()

        type_info = "YOLO -> Ded"
        completion = {
            "idScope": {
                "idImportedFrom" : {
                    "moduleName" : "Data.List"
                }
            },
            "idProp": {
                "idType" : "[a] -> a",
                "idName" : "head"
            }
        }

        # response = {"tag": "", "contents": [completion]}

        backend = MagicMock()

        # backend = FakeBackend(response)
        instance = stackide.StackIDE(view.window(), backend)
        # backend.handler = instance.handle_response
        stackide.StackIDE.ide_backend_instances[
            view.window().id()] = instance

        view.settings().get = Mock(return_value=False)
        listener.on_query_completions(view, 'm', []) #locations not used.

        view.settings().set.assert_called_with("refreshing_auto_complete", False)

        req = stackide.StackIDE.Req.get_autocompletion(filepath=stackide.relative_view_file_name(view),prefix="m")
        req['seq'] = ANY

        backend.send_request.assert_called_with(req)



class HandleResponseTests(unittest.TestCase):

    def test_handle_welcome_stack_ide_outdated(self):
        view = mock_view()
        backend = MagicMock()

        welcome = {
                  "tag": "ResponseWelcome",
                  "contents": [0, 0, 0]
                  }

        # backend = FakeBackend(response)
        instance = stackide.StackIDE(view.window(), backend)
        instance.handle_response(welcome)
        self.assertEqual(sublime.current_error, "Please upgrade stack-ide to a newer version.")

    def test_handle_update_progress(self):
        view = mock_view()
        backend = MagicMock()
        message = "Compiling (1/3) Main.hs"
        progress = {
                  "tag": "ResponseUpdateSession",
                  "contents": {
                    "progressParsedMsg": message
                    }
                  }

        # backend = FakeBackend(response)
        instance = stackide.StackIDE(view.window(), backend)
        instance.handle_response(progress)
        self.assertEqual(sublime.current_status, message)


if __name__ == '__main__':
    unittest.main()
