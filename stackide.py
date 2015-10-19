try:
    import sublime
    import sublime_plugin
except Exception:
    import mocks.sublime as sublime
    import mocks.sublime_plugin as sublime_plugin
import subprocess
import os
import sys
from itertools import groupby
import threading
import traceback
import json
import uuid
import glob


#############################
# Plugin development utils
#############################
# Ensure existing processes are killed when we
# save the plugin to prevent proliferation of
# stack-ide session.13953 folders

watchdog = None
supervisor = None

def plugin_loaded():
    global supervisor
    supervisor = Supervisor()

def plugin_unloaded():
    global supervisor
    supervisor.shutdown()
    supervisor = None
    # global watchdog
    # watchdog.kill()
    # StackIDE.reset()
    # Log.reset()
    # Settings.reset()
    # watchdog = None

class Supervisor():

    def __init__(self, monitor=True):
        self.settings = sublime.load_settings("SublimeStackIDE.sublime-settings")
        Log.normal("Starting Supervisor")
        self.window_instances = {}
        self.monitor = monitor
        self.timer = None
        self.check_instances()

    def check_instances(self):
        """
        Compares the current windows with the list of instances:
          - new windows are assigned a process of stack-ide each
          - stale processes are stopped

        NB. This is the only method that updates window_instance,
        so as long as it is not called concurrently, there will be no
        race conditions...
        """
        current_windows = {w.id(): w for w in sublime.windows()}
        updated_instances = {}

        # Kill stale instances, keep live ones
        for win_id, instance in self.window_instances.items():
            if win_id not in current_windows:
                # This is a window that is now closed, we may need to kill its process
                if instance.is_active:
                    Log.normal("Stopping stale process for window", win_id)
                    instance.end()
            else:
                # This window is still active. There are three possibilities:
                #  1) it has an alive and active instance.
                #  2) it has an alive but inactive instance (one that failed to init, etc)
                #  3) it has a dead instance, i.e., one that was killed.
                #
                # A window with a dead instances is treated like a new one, so we will
                # try to launch a new instance for it
                if instance.is_alive:
                    del current_windows[win_id]
                    updated_instances[win_id] = instance

        self.window_instances = updated_instances

        # The windows remaining in current_windows are new, so they have no instance.
        # We try to create one for them
        for window in current_windows.values():
            self.window_instances[window.id()] = launch_stack_ide(window)

        # schedule next run.
        if self.monitor:
            self.timer = threading.Timer(1.0, self.check_instances)
            self.timer.start()

    def shutdown(self):
        #todo: make sure processes are killed?
        if self.timer:
            self.timer.cancel()


#############################
# Utility functions
#############################

def first_folder(window):
    """
    We only support running one stack-ide instance per window currently,
    on the first folder open in that window.
    """
    if len(window.folders()):
        return window.folders()[0]
    else:
        Log.normal("Couldn't find a folder for stack-ide-sublime")
        return None

def has_cabal_file(project_path):
    """
    Check if a cabal file exists in the project folder
    """
    files = glob.glob(os.path.join(project_path, "*.cabal"))
    return len(files) > 0

def expected_cabalfile(project_path):
    """
    The cabalfile should have the same name as the directory it resides in (stack ide limitation?)
    """
    (_, project_name) = os.path.split(project_path)
    return os.path.join(project_path, project_name + ".cabal")

def is_stack_project(project_path):
    """
    Determine if a stack.yaml exists in the given directory.
    """
    return os.path.isfile(os.path.join(project_path, "stack.yaml"))

def relative_view_file_name(view):
    """
    ide-backend expects file names as relative to the cabal project root
    """
    return view.file_name().replace(first_folder(view.window()) + "/", "")

def send_request(window, request, on_response = None):
    """
    Sends the given request to the (view's) window's stack-ide instance,
    optionally handling its response
    """
    if StackIDE.is_running(window):
        StackIDE.for_window(window).send_request(request, on_response)

def get_view_selection(view):
    region = view.sel()[0]
    return (view.rowcol(region.begin()), view.rowcol(region.end()))

def span_from_view_selection(view):
    ((from_line, from_col), (to_line, to_col)) = get_view_selection(view)
    return {
        "spanFilePath": relative_view_file_name(view),
        "spanFromLine": from_line + 1,
        "spanFromColumn": to_col + 1,
        "spanToLine": to_line + 1,
        "spanToColumn": to_col + 1
        }

def view_region_from_span(view, span):
    """
    Maps a SourceSpan to a Region for a given view.

    :param sublime.View view: The view to create regions for
    :param SourceSpan span: The span to map to a region
    :rtype sublime.Region: The created Region

    """
    from_point = view.text_point(span.fromLine - 1, span.fromColumn - 1)
    to_point = view.text_point(span.toLine - 1, span.toColumn - 1)
    return sublime.Region(from_point, to_point)


def launch_stack_ide(window):
    """
    Launches a Stack IDE process for the current window if possible
    """
    folder = first_folder(window)

    if not folder:
        msg = "No folder to monitor for window " + str(window.id())
        Log.normal(msg)
        instance = NoStackIDE(msg)

    elif not has_cabal_file(folder):
        msg = "No cabal file found in " + folder
        Log.normal(msg)
        instance = NoStackIDE(msg)

    elif not os.path.isfile(expected_cabalfile(folder)):
        msg = "Expected cabal file " + expected_cabalfile(folder) + " not found"
        Log.warning(msg)
        instance = NoStackIDE(msg)

    elif not is_stack_project(folder):
        msg = "No stack.yaml in path " + folder
        Log.warning(msg)
        instance = NoStackIDE(msg)

        # TODO: We should also support single files, which should get their own StackIDE instance
        # which would then be per-view. Have a registry per-view that we check, then check the window.

    else:
        try:
            # If everything looks OK, launch a StackIDE instance
            Log.normal("Initializing window", window.id())

            # not clear how constructing an instance should throw a FileNotFoundError
            instance = StackIDE(window)
        except FileNotFoundError as e:
            instance = NoStackIDE("instance init failed -- stack not found")
            Log.error(e)
            cls.complain('stack-not-found',
                "Could not find program 'stack'!\n\n"
                "Make sure that 'stack' and 'stack-ide' are both installed. "
                "If they are not on the system path, edit the 'add_to_PATH' "
                "setting in SublimeStackIDE  preferences." )
        except Exception:
            instance = NoStackIDE("instance init failed -- unknown error")
            Log.error("Failed to initialize window " + str(window.id()) + ":")
            Log.error(traceback.format_exc())

    # Kick off the process by sending an initial request. We use another thread
    # to avoid any accidental blocking....
    def kick_off():
      Log.normal("Kicking off window", window.id())
      send_request(window,
        request     = StackIDE.Req.get_source_errors(),
        on_response = Win(window).highlight_errors
      )
    if not isinstance(instance, NoStackIDE):
        sublime.set_timeout_async(kick_off, 300)

    return instance

#############################
# Text commands
#############################

class ClearErrorPanelCommand(sublime_plugin.TextCommand):
    """
    A clear_error_panel command to clear the error panel.
    """
    def run(self, edit):
        self.view.erase(edit, sublime.Region(0, self.view.size()))

class UpdateErrorPanelCommand(sublime_plugin.TextCommand):
    """
    An update_error_panel command to append text to the error panel.
    """
    def run(self, edit, message):
        self.view.insert(edit, self.view.size(), message + "\n\n")

class ShowHsTypeAtCursorCommand(sublime_plugin.TextCommand):
    """
    A show_hs_type_at_cursor command that requests the type of the
    expression under the cursor and, if available, shows it as a pop-up.
    """
    def run(self,edit):
        request = StackIDE.Req.get_exp_types(span_from_view_selection(self.view))
        send_request(self.view.window(), request, self._handle_response)

    def _handle_response(self,response):
        types = list(parse_exp_types(response))
        if types:
            (type, span) = types[0]
            self.view.show_popup(type)


class ShowHsInfoAtCursorCommand(sublime_plugin.TextCommand):
    """
    A show_hs_info_at_cursor command that requests the info of the
    expression under the cursor and, if available, shows it as a pop-up.
    """
    def run(self,edit):
        request = StackIDE.Req.get_exp_info(span_from_view_selection(self.view))
        send_request(self.view.window(), request, self._handle_response)

    def _handle_response(self,response):

        if len(response) < 1:
           return

        infos = parse_span_info_response(response)
        (props, scope), span = next(infos)

        if not props.defSpan is None:
            source = "(Defined in {}:{}:{})".format(props.defSpan.filePath, props.defSpan.fromLine, props.defSpan.fromColumn)
        elif scope.importedFrom:
            source = "(Imported from {})".format(scope.importedFrom.module)

        self.view.show_popup("{} :: {}  {}".format(props.name,
                                                    props.type,
                                                    source))


class GotoDefinitionAtCursorCommand(sublime_plugin.TextCommand):
    """
    A goto_definition_at_cursor command that requests the info of the
    expression under the cursor and, if available, navigates to its location
    """
    def run(self,edit):
        request = StackIDE.Req.get_exp_info(span_from_view_selection(self.view))
        send_request(self.view.window() ,request, self._handle_response)

    def _handle_response(self,response):

        if len(response) < 1:
           return

        infos = parse_span_info_response(response)
        (props, scope), span = next(infos)
        window = self.view.window()
        if props.defSpan:
            full_path = os.path.join(first_folder(window), props.defSpan.filePath)
            window.open_file(
              '{}:{}:{}'.format(full_path, props.defSpan.fromLine or 0, props.defSpan.fromColumn or 0), sublime.ENCODED_POSITION)
        elif scope.importedFrom:
            sublime.status_message("Cannot navigate to {}, it is imported from {}".format(props.name, scope.importedFrom.module))
        else:
            sublime.status_message("{} not found!", props.name)


class CopyHsTypeAtCursorCommand(sublime_plugin.TextCommand):
    """
    A copy_hs_type_at_cursor command that requests the type of the
    expression under the cursor and, if available, puts it in the clipboard.
    """
    def run(self,edit):
        request = StackIDE.Req.get_exp_types(span_from_view_selection(self.view))
        send_request(self.view.window(), request, self._handle_response)

    def _handle_response(self,response):
        types = list(parse_exp_types(response))
        if types:
            (type, span) = types[0]
            sublime.set_clipboard(type)


#############################################
# PARSING
#
# see: https://github.com/commercialhaskell/stack-ide/blob/master/stack-ide-api/src/Stack/Ide/JsonAPI.hs
# and: https://github.com/fpco/ide-backend/blob/master/ide-backend-common/IdeSession/Types/Public.hs
# Types of responses:
# ResponseGetSourceErrors [SourceError]
# ResponseGetLoadedModules [ModuleName]
# ResponseGetSpanInfo [ResponseSpanInfo]
# ResponseGetExpTypes [ResponseExpType]
# ResponseGetAnnExpTypes [ResponseAnnExpType]
# ResponseGetAutocompletion [IdInfo]

def parse_autocompletions(contents):
    """
    Converts ResponseGetAutoCompletion content into [(IdProp, IdScope)]
    """
    return ((parse_idprop(item.get('idProp')),
            parse_idscope(item.get('idScope'))) for item in contents)


def parse_source_errors(contents):
    """
    Converts ResponseGetSourceErrors content into an array of SourceError objects
    """
    return (SourceError(item.get('errorKind'),
                        item.get('errorMsg'),
                        parse_either_span(item.get('errorSpan'))) for item in contents)


def parse_exp_types(contents):
    """
    Converts ResponseGetExpTypes contents into an array of pairs containing
    Text and SourceSpan
    Also see: type_info_for_sel (replace)
    """
    return ((item[0], parse_source_span(item[1])) for item in contents)


def parse_span_info(json):
    """
    Converts SpanInfo contents into a pair of IdProp and IdScope objects

    :param dict json: responds to a Span type from Stack IDE

    SpanInfo is either 'tag' SpanId or 'tag' SpanQQ, with an nested under as contents IdInfo
    TODO: deal with SpanQQ here
    """
    contents = json.get('contents')
    return (parse_idprop(contents.get('idProp')),
            parse_idscope(contents.get('idScope')))


def parse_span_info_response(contents):
    """
    Converts ResponseGetSpanInfo contents into an array of pairs of SpanInfo and SourceSpan objects
    ResponseGetSpanInfo's contents are an array of SpanInfo and SourceSpan pairs
    """
    return ((parse_span_info(responseSpanInfo[0]),
             parse_source_span(responseSpanInfo[1])) for responseSpanInfo in contents)


def parse_idprop(values):
    """
    Converts idProp content into an IdProp object.
    """
    return IdProp(values.get('idDefinedIn').get('moduleName'),
                    values.get('idDefinedIn').get('modulePackage').get('packageName'),
                    values.get('idType'),
                    values.get('idName'),
                    parse_either_span(values.get('idDefSpan')))


def parse_idscope(values):
    """
    Converts idScope content into an IdScope object (containing only an IdImportedFrom)
    """
    importedFrom = values.get('idImportedFrom')
    return IdScope(IdImportedFrom(importedFrom.get('moduleName'),
                                  importedFrom.get('modulePackage').get('packageName'))) if importedFrom else None


def parse_either_span(json):
    """
    Checks EitherSpan content and returns a SourceSpan if possible.
    """
    if json.get('tag') == 'ProperSpan':
        return parse_source_span(json.get('contents'))
    else:
        return None

def parse_source_span(json):
    """
    Converts json into a SourceSpan
    """
    paths = ['spanFilePath', 'spanFromLine', 'spanFromColumn', 'spanToLine', 'spanToColumn']
    fields = get_paths(paths, json)
    return SourceSpan(*fields) if fields else None


def get_paths(paths, values):
    """
    Converts a list of keypaths into an array of values from a dict
    """
    return list(values.get(path) for path in paths)


class SourceError():

    def __init__(self, kind, message, span):
        self.kind = kind
        self.msg = message
        self.span = span

    def __repr__(self):
        return "{file}:{from_line}:{from_column}: {kind}:\n{msg}".format(
            file=self.span.filePath,
            from_line=self.span.fromLine,
            from_column=self.span.fromColumn,
            kind=self.kind,
            msg=self.msg)


class SourceSpan():

    def __init__(self, filePath, fromLine, fromColumn, toLine, toColumn):
        self.filePath = filePath
        self.fromLine = fromLine
        self.fromColumn = fromColumn
        self.toLine = toLine
        self.toColumn = toColumn


class IdScope():

    def __init__(self, importedFrom):
        self.importedFrom = importedFrom

class IdImportedFrom():

    def __init__(self, module, package):
        self.module = module
        self.package = package

class IdProp():

    def __init__(self, package, module, type, name, defSpan):
        self.package = package
        self.module = module
        self.type = type
        self.name = name
        self.defSpan = defSpan


#############################
# Event Listeners
#############################

class StackIDESaveListener(sublime_plugin.EventListener):
    """
    Ask stack-ide to recompile the saved source file,
    then request a report of source errors.
    """
    def on_post_save(self, view):
        window = view.window()
        if not StackIDE.is_running(window):
            return

        # This works to load the saved file into stack-ide, but since it doesn't the include dirs
        # (we don't have the API for that yet, though it wouldn't be hard to add) it won't see any modules.
        # request = {
        #     "tag":"RequestUpdateSession",
        #     "contents":
        #         [ { "tag": "RequestUpdateTargets",
        #             "contents": {"tag": "TargetsInclude", "contents":[ relative_view_file_name(view) ]}
        #           }
        #         ]
        #     }
        send_request(window, StackIDE.Req.update_session())
        send_request(window, StackIDE.Req.get_source_errors(), Win(window).highlight_errors)

class StackIDETypeAtCursorHandler(sublime_plugin.EventListener):
    """
    Ask stack-ide for the type at the cursor each
    time it changes position.
    """
    def on_selection_modified(self, view):
        if not view:
            return
        window = view.window()
        if not StackIDE.is_running(window):
            return
        # Only try to get types for views into files
        # (rather than e.g. the find field or the console pane)
        if view.file_name():
            # Uncomment to see the scope at the cursor:
            # Log.debug(view.scope_name(view.sel()[0].begin()))
            request = StackIDE.Req.get_exp_types(span_from_view_selection(view))
            send_request(window, request, Win(window).highlight_type)


class StackIDEAutocompleteHandler(sublime_plugin.EventListener):
    """
    Dispatches autocompletion requests to stack-ide.
    """
    def __init__(self):
        super(StackIDEAutocompleteHandler, self).__init__()
        self.returned_completions = []
        self.view = None
        self.refreshing = False

    def on_query_completions(self, view, prefix, locations):

        window = view.window()
        if not StackIDE.is_running(window):
            return
        # Check if this completion query is due to our refreshing the completions list
        # after receiving a response from stack-ide, and if so, don't send
        # another request for completions.
        if not self.refreshing:
            self.view = view
            request = StackIDE.Req.get_autocompletion(filepath=relative_view_file_name(view),prefix=prefix)
            send_request(window, request, self._handle_response)

        # Clear the flag to allow future completion queries
        self.refreshing = False
        return list(self.format_completion(*completion) for completion in self.returned_completions)


    def format_completion(self, prop, scope):
        return ["{}\t{}\t{}".format(prop.name,
                                    prop.type or '',
                                    scope.importedFrom.module if scope else ''),
                 prop.name]

    def _handle_response(self, response):
        self.returned_completions = list(parse_autocompletions(response))
        self.view.run_command('hide_auto_complete')
        sublime.set_timeout(self.run_auto_complete, 0)


    def run_auto_complete(self):
        self.refreshing = True
        self.view.run_command("auto_complete", {
            'disable_auto_insert': True,
            # 'api_completions_only': True,
            'next_completion_if_showing': False,
            # 'auto_complete_commit_on_tab': True,
        })

#############################
# Window commands
#############################

class SendStackIdeRequestCommand(sublime_plugin.WindowCommand):
    """
    Allows sending commands via
    window.run_command("send_stack_ide_request", {"request":{"my":"request"}})
    (Sublime Text uses the class name to determine the name of the command
    the class executes when called)
    """

    def __init__(self, window):
        super(SendStackIdeRequestCommand, self).__init__(window)

    def run(self, request):
        """
        Pass a request to stack-ide.
        Called via run_command("send_stack_ide_request", {"request":})
        """
        instance = StackIDE.for_window(self.window)
        if instance:
            instance.send_request(request)

##########################
# Application Commands
##########################
class RestartStackIde(sublime_plugin.ApplicationCommand):
    """
    Restarts the StackIDE plugin.
    Useful for forcing StackIDE to pick up project changes, until we implement it properly.
    Accessible via the Command Palette (Cmd/Ctrl-Shift-p)
    as "SublimeStackIDE: Restart"
    """
    def run(self):
        StackIDE.reset()


class JsonProcessBackend:
    """
    Handles process communication with JSON.
    """
    def __init__(self, process, response_handler):
        self._process = process
        self._response_handler = response_handler
        self.stdoutThread = threading.Thread(target=self.read_stdout)
        self.stdoutThread.start()
        self.stderrThread = threading.Thread(target=self.read_stderr)
        self.stderrThread.start()

    def send_request(self, request):

        try:
            Log.debug("Sending request: ", request)
            encodedString = json.JSONEncoder().encode(request) + "\n"
            self._process.stdin.write(bytes(encodedString, 'UTF-8'))
            self._process.stdin.flush()
        except BrokenPipeError as e:
            Log.error("stack-ide unexpectedly died:",e)

            # self.die()
                # Ideally we would like to die(), so that, if the error is transient,
                # we attempt to reconnect on the next check_windows() call. The problem
                # is that the stack-ide (ide-backend, actually) is not cleaning up those
                # session.* directories and they would keep accumulating, one per second!
                # So instead we do:
            self.is_active = False


    def read_stderr(self):
        """
        Reads any errors from the stack-ide process.
        """
        while self._process.poll() is None:
            try:
                Log.warning("Stack-IDE error: ", self._process.stderr.readline().decode('UTF-8'))
            except:
                Log.error("Stack-IDE stderr process ending due to exception: ", sys.exc_info())
                return;
        Log.normal("Stack-IDE stderr process ended.")

    def read_stdout(self):
        """
        Reads JSON responses from stack-ide and dispatch them to
        various main thread handlers.
        """
        while self._process.poll() is None:
            try:
                raw = self._process.stdout.readline().decode('UTF-8')
                if not raw:
                    return

                data = None
                try:
                    data = json.loads(raw)
                except:
                    Log.debug("Got a non-JSON response: ", raw)
                    continue

                #todo: try catch ?
                self._response_handler(data)

            except:
                Log.warning("Stack-IDE stdout process ending due to exception: ", sys.exc_info())
                self._process.terminate()
                self._process = None
                return;

        Log.normal("Stack-IDE stdout process ended.")

def boot_ide_backend(path, response_handler):
    """
    Start up a stack-ide subprocess for the window, and a thread to consume its stdout.
    """
    Log.normal("Launching stack-ide instance for ", path)

    # Assumes the library target name is the same as the project dir
    (project_in, project_name) = os.path.split(path)

    # Extend the search path if indicated
    alt_env = os.environ.copy()
    add_to_PATH = Settings.add_to_PATH()
    if len(add_to_PATH) > 0:
      alt_env["PATH"] = os.pathsep.join(add_to_PATH + [alt_env.get("PATH","")])

    Log.debug("Calling stack with PATH:", alt_env['PATH'] if alt_env else os.environ['PATH'])

    process = subprocess.Popen(["stack", "ide", "start", project_name],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=path, env=alt_env
        )

    return JsonProcessBackend(process, response_handler)


class StackIDE:
    ide_backend_instances = {}
    complaints_shown = set()

    class Req:

        @staticmethod
        def update_session():
            return { "tag":"RequestUpdateSession", "contents": []}

        @staticmethod
        def get_source_errors():
            return {"tag": "RequestGetSourceErrors", "contents": []}

        @staticmethod
        def get_exp_types(exp_span):
            return { "tag": "RequestGetExpTypes", "contents": exp_span}

        @staticmethod
        def get_exp_info(exp_span):
            return { "tag": "RequestGetSpanInfo", "contents": exp_span}

        @staticmethod
        def get_autocompletion(filepath,prefix):
            return {
                "tag":"RequestGetAutocompletion",
                "contents": [
                        filepath,
                        prefix
                    ]
                }
        @staticmethod
        def get_shutdown():
            return { "tag": "RequestShutdownSession", "contents":[]}

    @classmethod
    def is_running(cls, window):
        if not window:
            return False
        return StackIDE.for_window(window) is not None


    @classmethod
    def for_window(cls, window):
        instance = StackIDE.ide_backend_instances.get(window.id())
        if instance and not instance.is_active:
            instance = None

        return instance

    @classmethod
    def kill_all(cls):
        Log.normal("Killing all stack-ide-sublime instances:", {k:str(v) for k,v in StackIDE.ide_backend_instances.items()})
        for instance in StackIDE.ide_backend_instances.values():
            instance.end()

    @classmethod
    def reset(cls):
        """
        Kill all instances, and forget about previous notifications.
        """
        Log.normal("Resetting StackIDE")
        cls.kill_all()
        cls.complaints_shown = set()


    @classmethod
    def complain(cls,complaint_id,msg):
       """
       Show the msg as an error message (on a modal pop-up). The complaint_id is
       used to decide when we have already complained about something, so that
       we don't do it again (until reset)
       """
       if complaint_id not in cls.complaints_shown:
           cls.complaints_shown.add(complaint_id)
           sublime.error_message(msg)


    def __init__(self, window, backend=None):
        self.window = window
        self.conts = {} # Map from uuid to response handler
        self.is_alive  = True
        self.is_active = False
        self.process   = None
        if backend is None:
            self._backend = boot_ide_backend(first_folder(window), self.handle_response)
        else:
            self._backend = backend

        self.is_active = True

    def send_request(self, request, response_handler=None):
        """
        Associates requests with handlers and passes them on to the process.
        """
        if self._backend:
            if response_handler is not None:
                seq_id = str(uuid.uuid4())
                self.conts[seq_id] = response_handler
                request = request.copy()
                request['seq'] = seq_id

            self._backend.send_request(request)
        else:
            Log.error("Couldn't send request, no process!", request)

    def end(self):
        """
        Ask stack-ide to shut down.
        """
        self.send_request(self.Req.get_shutdown())
        self.die()

    def die(self):
        """
        Mark the instance as no longer alive
        """
        self.is_alive = False
        self.is_active = False


    def handle_response(self, data):
        """
        Handles JSON responses from the backend
        """
        # Log.debug("Got response: ", data)

        response = data.get("tag")
        contents = data.get("contents")
        seq_id   = data.get("seq")

        if seq_id is not None:
            handler = self.conts.get(seq_id)
            del self.conts[seq_id]
            if handler is not None:
                if contents is not None:
                    sublime.set_timeout(lambda:handler(contents), 0)
            else:
                Log.warning("Handler not found for seq", seq_id)
        # Check that stack-ide talks a version of the protocal we understand
        elif response == "ResponseWelcome":
            expected_version = (0,1,1)
            version_got = tuple(contents) if type(contents) is list else contents
            if expected_version > version_got:
                Log.error("Old stack-ide protocol:", version_got, '\n', 'Want version:', expected_version)
                StackIDE.complain("wrong-stack-ide-version",
                    "Please upgrade stack-ide to a newer version.")
            elif expected_version < version_got:
                Log.warning("stack-ide protocol may have changed:", version_got)
            else:
                Log.debug("stack-ide protocol version:", version_got)
        # # Pass progress messages to the status bar
        elif response == "ResponseUpdateSession":
            if contents != None:
                progressMessage = contents.get("progressParsedMsg")
                if progressMessage:
                    sublime.status_message(progressMessage)
        else:
            Log.normal("Unhandled response: ", data)


    def __del__(self):
        if self.process:
            try:
                self.process.terminate()
            except ProcessLookupError:
                # it was already done...
                pass
            finally:
                self.process = None


class NoStackIDE:
    """
    Objects of this class are used for windows that don't have an associated stack-ide process
    (e.g., because initialization failed or they are not being monitored)
    """

    def __init__(self, reason):
        self.is_alive = True
        self.is_active = False
        self.reason = reason

    def end(self):
        self.is_alive = False

    def __str__(self):
        return 'NoStackIDE(' + self.reason + ')'


class Win:
    """
    Operations on Sublime windows that are relevant to us
    """

    def __init__(self, window):
        self.window = window

    def highlight_type(self, exp_types):
        """
        ide-backend gives us a wealth of type info for the cursor. We only use the first,
        most specific one for now, but it gives us the types all the way out to the topmost
        expression.
        """
        types = list(parse_exp_types(exp_types))
        if types:
            # Display the first type in a region and in the status bar
            view = self.window.active_view()
            (type, span) = types[0] # type_info_for_sel(view, types)
            if span:
                if Settings.show_popup():
                    view.show_popup(type)
                view.set_status("type_at_cursor", type)
                view.add_regions("type_at_cursor", [view_region_from_span(view, span)], "storage.type", "", sublime.DRAW_OUTLINED)
        else:
            # Clear type-at-cursor display
            for view in self.window.views():
                view.set_status("type_at_cursor", "")
                view.add_regions("type_at_cursor", [], "storage.type", "", sublime.DRAW_OUTLINED)


    def find_view_for_path(self, file_path):
        full_path = os.path.join(first_folder(self.window), file_path)
        return self.window.find_open_file(full_path)

    def reset_error_panel(self):
        """
        Creates and configures the error panel for the current window
        """
        panel = self.window.create_output_panel("hide_errors")
        panel.set_read_only(False)

        # This turns on double-clickable error/warning messages in the error panel
        # using a regex that looks for the form file_name:line:column
        panel.settings().set("result_file_regex", "^(..[^:]*):([0-9]+):?([0-9]+)?:? (.*)$")

        # Seems to force the panel to refresh after we clear it:
        self.window.run_command("hide_panel", {"panel": "output.hide_errors"})

        # Clear the panel
        panel.run_command("clear_error_panel")

        return panel


    def highlight_errors(self, source_errors):
        """
        Places errors in the error panel, and highlights the relevant regions for each error.
        """

        errors = list(parse_source_errors(source_errors))

        # TODO we should pass the errorKind too if the error has no span
        # TODO check if errors without span occur and work?
        error_panel = self.reset_error_panel()
        for error in errors:
            error_panel.run_command("update_error_panel", {"message": repr(error)})

        # We gather each error by the file view it should annotate
        # so we can add regions in bulk to each view.
        error_regions_by_view_id = {}
        warning_regions_by_view_id = {}
        for path, errors in groupby(errors, lambda error: error.span.filePath):
            view = self.find_view_for_path(path)
            for kind, errors in groupby(errors, lambda error: error.kind):
                if kind == 'KindWarning':
                    warning_regions_by_view_id[view.id()] = list(view_region_from_span(view, error.span) for error in errors)
                else:
                    error_regions_by_view_id[view.id()] = list(view_region_from_span(view, error.span) for error in errors)

        # Add error/warning regions to their respective views
        for view in self.window.views():
            view.add_regions("errors", error_regions_by_view_id.get(view.id(), []), "invalid", "dot", sublime.DRAW_OUTLINED)
            view.add_regions("warnings", warning_regions_by_view_id.get(view.id(), []), "comment", "dot", sublime.DRAW_OUTLINED)

        if errors:
            self.window.run_command("show_panel", {"panel":"output.hide_errors"})
        else:
            self.window.run_command("hide_panel", {"panel":"output.hide_errors"})

        error_panel.set_read_only(True)


class Settings:

    # This is the sublime.Settings object associated to "SublimeStackIDE.sublime-settings".
    # The Sublime API guarantees that no matter how many times we call sublime.load_settings(),
    # we will always get the same object, so it is safe to save it (in particular, this means
    # that if the user modifies the settings, they will be reflected on this object (one can
    # then use settings.add_on_change() to register a callback, when a reaction is needed).
    settings = None

    @classmethod
    def _get(cls,key,default):
        cls.lazy_init()
        return cls.settings.get(key,default)


    @classmethod
    def lazy_init(cls):
        if cls.settings is None:
            cls.settings = sublime.load_settings("SublimeStackIDE.sublime-settings")
            cls.settings.add_on_change("_on_new_settings",Settings._on_new_settings)

    @staticmethod
    def _on_new_settings():
      Log.reset()
      StackIDE.reset()
        # Whenever the add_to_PATH setting changes, it can be that a) instances
        # that failed to be initialized since 'stack' was not found, now have a
        # chance of being functional, or b) the user wants to use another version
        # of stack / stack-ide. In any case, we start again...

    @classmethod
    def reset(cls):
      """
      Removes settings listeners
      """
      if cls.settings:
        cls.settings.clear_on_change("_on_new_settings")
        cls.settings = None

    @classmethod
    def add_to_PATH(cls):
        val = cls._get("add_to_PATH", [])
        if not isinstance(val,list):
            val = []
        return val

    @classmethod
    def show_popup(cls):
        val = cls._get("show_popup", False)
        return val

    @classmethod
    def verbosity(cls):
        return cls._get("verbosity","warning")

class Log:
  """
  Logging facilities
  """

  verbosity = None

  VERB_NONE    = 0
  VERB_ERROR   = 1
  VERB_WARNING = 2
  VERB_NORMAL  = 3
  VERB_DEBUG   = 4

  @classmethod
  def reset(cls):
      Log.verbosity = None

  @classmethod
  def error(cls,*msg):
      Log._record(Log.VERB_ERROR, *msg)

  @classmethod
  def warning(cls,*msg):
      Log._record(Log.VERB_WARNING, *msg)

  @classmethod
  def normal(cls,*msg):
      Log._record(Log.VERB_NORMAL, *msg)

  @classmethod
  def debug(cls,*msg):
      Log._record(Log.VERB_DEBUG, *msg)

  @classmethod
  def _record(cls, verb, *msg):
      if not Log.verbosity:
          Log.set_verbosity("debug")

      if verb <= Log.verbosity:
          for line in ''.join(map(lambda x: str(x), msg)).split('\n'):
              print('SublimeStackIDE ['+cls._show_verbosity(verb)+']:', msg)

          if verb == Log.VERB_ERROR:
              sublime.status_message('There were errors, check the console log')
          elif verb == Log.VERB_WARNING:
              sublime.status_message('There were warnings, check the console log')


  @classmethod
  def set_verbosity(cls, verb):

      if verb == "none":
          Log.verbosity = Log.VERB_NONE
      elif verb == "error":
          Log.verbosity = Log.VERB_ERROR
      elif verb == "warning":
          Log.verbosity = Log.VERB_WARNING
      elif verb == "normal":
          Log.verbosity = Log.VERB_NORMAL
      elif verb == "debug":
          Log.verbosity = Log.VERB_DEBUG
      else:
          Log.verbosity = Log.VERB_WARNING
          Log.warning("Invalid verbosity: '" + str(verb) + "'")

  @classmethod
  def _show_verbosity(cls,verb):
      return ["?!","ERROR","WARN","NORM","DEBUG"][verb]
