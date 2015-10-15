try:
    import sublime
    import sublime_plugin
except Exception:
    import mocks.sublime as sublime
    import mocks.sublime_plugin as sublime_plugin
import subprocess
import os
import sys
import threading
import traceback
import json
import uuid
import glob

# TODO: look at Tern_for_sublime's implementation.
# Logging is a bit complicated for what it does
# Is reloading logic needed (does the trigger even work?)
# Keep commands / listener(s) short (seperate files?) and hook them up via functions.

#############################
# Plugin development utils
#############################
# Ensure existing processes are killed when we
# save the plugin to prevent proliferation of
# stack-ide session.13953 folders

watchdog = None

def plugin_loaded():
    global watchdog
    watchdog = StackIDEWatchdog()

def plugin_unloaded():
    global watchdog
    watchdog.kill()
    StackIDE.reset()
    Log.reset()
    Settings.reset()
    watchdog = None

class Supervisor():

    def __init__(self):
        self.settings = sublime.load_settings()
        self.window_instances = {}
        self.check_instances()

    def check_instances(self):
        """
        Compares the current windows with the list of instances:
          - new windows are assigned a process of stack-ide each
          - stale processes are stopped

        NB. This is the only method that updates ide_backend_instances,
        so as long as it is not called concurrently, there will be no
        race conditions...
        """
        current_windows = {w.id(): w for w in sublime.windows()}
        updated_instances = {}

        # Kill stale instances, keep live ones
        for win_id, instance in StackIDE.ide_backend_instances.items():
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

        # Thw windows remaining in current_windows are new, so they have no instance.
        # We try to create one for them
        for window in current_windows.values():
            self.window_instances[window.id()] = launch_stack_ide(window)


class StackIDEWatchdog():
    """
    Since I can't find any way to detect if a window closes,
    we use a watchdog timer to clean up stack-ide instances
    once we see that the window is no longer in existence.
    """
    def __init__(self):
        super(StackIDEWatchdog, self).__init__()
        Log.normal("Starting stack-ide-sublime watchdog")
        self.check_for_processes()

    def check_for_processes(self):
        StackIDE.check_windows()
        self.timer = threading.Timer(1.0, self.check_for_processes)
        self.timer.start()

    def kill(self):
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

# why span[1] ?
def filter_enclosing(from_col, to_col, from_line, to_line, spans):
    """
    spans are considered enclosing if line starts before or col starts before
    and line ends after or col ends after given from / to values.
    """
    return [span for span in spans if
        (   ((span[1].get("spanFromLine")<from_line) or
            (span[1].get("spanFromLine") == from_line and
             span[1].get("spanFromColumn") <= from_col))
        and ((span[1].get("spanToLine")>to_line) or
            (span[1].get("spanToLine") == to_line and
             span[1].get("spanToColumn") >= to_col))
        )]

def type_info_for_sel(view,types):
    """
    Takes the type spans returned from a get_exp_types request and returns a
    tuple (type_string,type_span) of the main expression
    """
    result = None
    if view and types:
        ((from_line_, from_col_), (to_line_, to_col_)) = get_view_selection(view)
        [type_string, type_span] = filter_enclosing(
            from_col_+1, to_col_+1,
            from_line_+1, to_line_+1,
            types)[0]
        result = (type_string, type_span)
    return result


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
        send_request(self.view,request, self._handle_response)

    def _handle_response(self,response):
        info = type_info_for_sel(self.view,response)
        if info:
            (type_str,type_span) = info
            self.view.show_popup(type_str)


class ShowHsInfoAtCursorCommand(sublime_plugin.TextCommand):
    """
    A show_hs_info_at_cursor command that requests the info of the
    expression under the cursor and, if available, shows it as a pop-up.
    """
    def run(self,edit):
        request = StackIDE.Req.get_exp_info(span_from_view_selection(self.view))
        send_request(self.view,request, self._handle_response)

    def _handle_response(self,response):

        if len(response) < 1:
           return

        contents = response[0][0]["contents"]
        info = parse_info_result(response[0][0]["contents"])

        if info.file:
            source = "(Defined in {}:{}:{})".format(info.file, info.line, info.col)
        elif info.module:
            source = "(Imported from {})".format(info.module)

        self.view.show_popup("{} :: {}  {}".format(info.name,
                                                    info.type,
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

        info = parse_info_result(response[0][0]["contents"])
        window = self.view.window()
        if info.file:
            full_path = os.path.join(first_folder(window), info.file)
            window.open_file(
              '{}:{}:{}'.format(full_path, info.line or 0, info.col or 0), sublime.ENCODED_POSITION)
        elif info.module:
            sublime.status_message("Cannot navigate to {}, it is imported from {}".format(info.name, info.module))
        else:
            sublime.status_message("{} not found!", info.name)


class CopyHsTypeAtCursorCommand(sublime_plugin.TextCommand):
    """
    A copy_hs_type_at_cursor command that requests the type of the
    expression under the cursor and, if available, puts it in the clipboard.
    """
    def run(self,edit):
        request = StackIDE.Req.get_exp_types(span_from_view_selection(self.view))
        send_request(self.view.window(), request, self._handle_response)

    def _handle_response(self,response):
        info = type_info_for_sel(self.view,response)
        if info:
            (type_str,type_span) = info
            sublime.set_clipboard(type_str)

def parse_info_result(contents):
    """
    Extracts reponse into a reusable expression info object
    """
    module_keypath = ["idScope", "idImportedFrom", "moduleName"]
    type_keypath   = ["idProp", "idType"]
    name_keypath   = ["idProp", "idName"]
    def_file_keypath   = ["idProp", "idDefSpan", "contents", "spanFilePath"]
    def_line_keypath      = ["idProp", "idDefSpan", "contents", "spanFromLine"]
    def_col_keypath       = ["idProp", "idDefSpan", "contents", "spanFromColumn"]

    return ExpressionInfo(get_keypath(contents, name_keypath),
                            get_keypath(contents, type_keypath),
                            get_keypath(contents, module_keypath),
                            get_keypath(contents, def_file_keypath),
                            get_keypath(contents, def_line_keypath),
                            get_keypath(contents, def_col_keypath))

class ExpressionInfo():

    def __init__(self, name, type, module, file, line, col):
        self.name = name
        self.type = type
        self.module = module
        self.file = file
        self.line = line
        self.col = col


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
        request = {
            "tag":"RequestUpdateSession",
            "contents": []
            }
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
        send_request(window, request)
        send_request(window, StackIDE.Req.get_source_errors(),Win(window).highlight_errors)

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

def get_keypath(a_dict, keypath):
    """
    Extracts a keypath from a nested dictionary, e.g.
    >>> get_keypath({"hey":{"there":"kid"}}, ["hey", "there"])
    'kid'
    Returns None if the keypath doesn't exist.
    """
    value = a_dict
    path = keypath
    while value and path:
        if not type(value) is dict: return None
        value = value.get(path[0])
        path = path[1:]
    return value

class StackIDEAutocompleteHandler(sublime_plugin.EventListener):
    """
    Dispatches autocompletion requests to stack-ide.
    """
    def __init__(self):
        super(StackIDEAutocompleteHandler, self).__init__()
        self.returned_completions = []

    def on_query_completions(self, view, prefix, locations):

        window = view.window()
        if not StackIDE.is_running(window):
            return
        # Check if this completion query is due to our refreshing the completions list
        # after receiving a response from stack-ide, and if so, don't send
        # another request for completions.
        if not view.settings().get("refreshing_auto_complete"):
            request = StackIDE.Req.get_autocompletion(filepath=relative_view_file_name(view),prefix=prefix)
            send_request(window, request, Win(window).update_completions)

        # Clear the flag to uninhibit future completion queries
        view.settings().set("refreshing_auto_complete", False)

        # Sublime Text 3 expects completions in the form of [(annotation, name)],
        # where annotation is <name>\t<hint1>\t<hint2>
        # where hint1/hint2/etc. are optional auxiliary information that will
        # be displayed in italics to the right of the name.
        module_keypath = ["idScope", "idImportedFrom", "moduleName"]
        type_keypath   = ["idProp", "idType"]
        name_keypath   = ["idProp", "idName"]
        keypaths       = [name_keypath, type_keypath, module_keypath]
        def annotation_from_completion(completion):
            return "\t".join(
                filter(lambda x: x is not None,
                    map(lambda keypath: get_keypath(completion, keypath),
                        keypaths)))

        annotations = map(annotation_from_completion, self.returned_completions)
        names       = map(lambda completion: get_keypath(completion, name_keypath), self.returned_completions)

        annotated_completions = list(zip(annotations, names))
        Log.debug("Returning: ", annotated_completions)
        return annotated_completions


    def on_window_command(self, window, command_name, args):
        """
        Implements a hacky way of returning data to the StackIDEAutocompleteHandler instance,
        wherein SendStackIDERequestCommand calls a update_completions command on the window,
        which is really just a dummy command that we intercept here in order to assign the resulting
        completions to returned_completions to then, finally, return the next time on_query_completions
        is called.
        """
        if not StackIDE.is_running(window):
            return
        if args == None:
            return None
        completions = args.get("completions")
        if command_name == "update_completions" and completions:
            # Log.debug("INTERCEPTED:\n " + str(completions) + "\n")
            self.returned_completions = completions

            # Hide the auto_complete popup so we can reopen it,
            # triggering a new on_query_completions
            # call to pickup our new self.returned_completions.
            window.active_view().run_command('hide_auto_complete')

            def reactivate():
                # We read this in on_query_completions to prevent sending a duplicate
                # request for completions when we're only trying to re-trigger the completions
                # popup; otherwise we get an infinite loop of
                #   autocomplete > request completions > receive response > close/reopen to refresh
                # > autocomplete > request completions > etc.
                window.active_view().settings().set("refreshing_auto_complete", True)
                window.active_view().run_command('auto_complete', {
                        'disable_auto_insert': True,
                        # 'api_completions_only': True,
                        'next_competion_if_showing': False
                    })
            # Wait one runloop before reactivating, to give the hide command a chance to finish
            sublime.set_timeout(reactivate, 0)
        return None

#############################
# Window commands
#############################

class UpdateCompletionsCommand(sublime_plugin.WindowCommand):
    """
    This class only exists so that the command can be called and intercepted by
    StackIDEAutocompleteHandler to update its completions list.
    """
    def run(self, completions):
        return None

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
        while self.process.poll() is None:
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
        def get_source_errors():
            return {"tag": "RequestGetSourceErrors", "contents":[]}

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
    def check_windows(cls):
        """
        Compares the current windows with the list of instances:
          - new windows are assigned a process of stack-ide each
          - stale processes are stopped

        NB. This is the only method that updates ide_backend_instances,
        so as long as it is not called concurrently, there will be no
        race conditions...
        """
        current_windows = {w.id(): w for w in sublime.windows()}
        updated_instances = {}

        # Kill stale instances, keep live ones
        for win_id,instance in StackIDE.ide_backend_instances.items():
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

        StackIDE.ide_backend_instances = updated_instances

        # Thw windows remaining in current_windows are new, so they have no instance.
        # We try to create one for them
        for window in current_windows.values():
            StackIDE.ide_backend_instances[window.id()] = launch_stack_ide(window)

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

        Log.debug("Got response: ", data)

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


    def update_completions(self, completions):
        """
        Dispatches to the dummy UpdateCompletionsCommand, which is intercepted
        by StackIDEAutocompleteHandler's on_window_command to update its list
        of completions.
        """
        self.window.run_command("update_completions", {"completions":completions})


    def highlight_type(self, types):
        """
        ide-backend gives us a wealth of type info for the cursor. We only use the first,
        most specific one for now, but it gives us the types all the way out to the topmost
        expression.
        """
        if types:
            # Display the first type in a region and in the status bar
            view = self.window.active_view()
            (type_string,type_span) = type_info_for_sel(view,types)
            span = Span.from_json(type_span, self.window)
            if span:
                if Settings.show_popup():
                    view.show_popup(type_string)
                view.set_status("type_at_cursor", type_string)
                view.add_regions("type_at_cursor", [span.in_view.region], "storage.type", "", sublime.DRAW_OUTLINED)
        else:
            # Clear type-at-cursor display
            for view in self.window.views():
                view.set_status("type_at_cursor", "")
                view.add_regions("type_at_cursor", [], "storage.type", "", sublime.DRAW_OUTLINED)


    def highlight_errors(self, errors):
        """
        Places errors in the error panel, and highlights the relevant regions for each error.
        """
        error_panel = self.window.create_output_panel("hide_errors")
        error_panel.set_read_only(False)

        # This turns on double-clickable error/warning messages in the error panel
        # using a regex that looks for the form file_name:line:column
        error_panel.settings().set("result_file_regex","^(..[^:]*):([0-9]+):?([0-9]+)?:? (.*)$")

        # Seems to force the panel to refresh after we clear it:
        self.window.run_command("hide_panel", {"panel":"output.hide_errors"})
        # Clear the panel
        error_panel.run_command("clear_error_panel")

        # We gather each error by the file view it should annotate
        # so we can add regions in bulk to each view.
        errors_by_view_id = {}
        warnings_by_view_id = {}
        for error in errors:
            proper_span = error.get("errorSpan")

            # Stack-ide can return different kinds of Spans for errors; we only support ProperSpans currently
            span = None
            if proper_span.get("tag") == "ProperSpan":
                span = Span.from_json(proper_span.get("contents"), self.window)

            # Text commands only accept Value types, so we perform the conversion of the error span to a string here
            # to pass to update_error_panel.
            # TODO we should pass the errorKind too if the error has no span
            message = span.as_error_message(error) if span else error.get("errorMsg")

            # Add the error to the error panel
            error_panel.run_command("update_error_panel", {"message":message})

            # Collect error and warning spans by view for annotations
            span_view = span.in_view if span else None
            if span_view:
                # Log.debug("Adding error at "+ str(span) + ": " + str(error.get("errorMsg")))
                kind = error.get("errorKind")
                if kind == "KindWarning":
                    warning_regions_for_view = warnings_by_view_id.get(span_view.view.id(), [])
                    warning_regions_for_view += [span_view.region]
                    warnings_by_view_id[span_view.view.id()] = warning_regions_for_view
                else:
                    error_regions_for_view = errors_by_view_id.get(span_view.view.id(), [])
                    error_regions_for_view += [span_view.region]
                    errors_by_view_id[span_view.view.id()] = error_regions_for_view

            else:
                Log.warning("Unhandled error tag type: ", proper_span)

        # Add error/warning regions to their respective views
        for view in self.window.views():
            # Return an empty list if there are no errors for the view, so that we clear the error regions
            error_regions = errors_by_view_id.get(view.id(), [])
            view.add_regions("errors", error_regions, "invalid", "dot", sublime.DRAW_OUTLINED)
            warning_regions = warnings_by_view_id.get(view.id(), [])
            view.add_regions("warnings", warning_regions, "comment", "dot", sublime.DRAW_OUTLINED)

        if errors:
            # Show the panel
            self.window.run_command("show_panel", {"panel":"output.hide_errors"})
        else:
            # Hide the panel
            self.window.run_command("hide_panel", {"panel":"output.hide_errors"})

        error_panel.set_read_only(True)


class Span:
    """
    Represents the Stack-IDE 'span' type
    """

    class InView:
        """
        When a span corresponds to a file being displayed in a view,
        this object holds the position of the span inside that view.
        """

        def __init__(self, view, from_point, to_point, region):
            self.view           = view
            self.from_point     = from_point
            self.to_point       = to_point
            self.region         = region

    @classmethod
    def from_json(cls, span, window):
        file_path    = span.get("spanFilePath")
        if file_path == None:
            return None
        from_line    = span.get("spanFromLine")
        from_column  = span.get("spanFromColumn")
        to_line      = span.get("spanToLine")
        to_column    = span.get("spanToColumn")

        full_path    = first_folder(window) + "/" + file_path
        view         = window.find_open_file(full_path)
        if view is None:
            in_view = None
        else:
            from_point = view.text_point(from_line - 1, from_column - 1)
            to_point   = view.text_point(to_line   - 1, to_column   - 1)
            region     = sublime.Region(from_point, to_point)

            in_view    = Span.InView(view, from_point, to_point, region)

        return Span(from_line, from_column, to_line, to_column, full_path, in_view)

    def __init__(self, from_line, from_column, to_line, to_column, full_path, in_view):
        self.from_line      = from_line
        self.from_column    = from_column
        self.to_line        = to_line
        self.to_column      = to_column
        self.full_path      = full_path
        self.in_view        = in_view

    def as_error_message(self, error):
        kind      = error.get("errorKind")
        error_msg = error.get("errorMsg")

        return "{file}:{from_line}:{from_column}: {kind}:\n{msg}".format(
            file=self.full_path,
            from_line=self.from_line,
            from_column=self.from_column,
            kind=kind,
            msg=error_msg)


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
          Log.set_verbosity("normal")

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
