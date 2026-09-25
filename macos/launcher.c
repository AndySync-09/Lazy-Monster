/* Lazy-Monster.app launcher.
 * macOS grants Microphone, Accessibility, Screen Recording, Input Monitoring and Automation to an *app*.
 * This tiny executable is that app: it starts the monster's Python as its child, so every permission
 * prompt and every switch in Privacy & Security says "Lazy-Monster" instead of Python or Terminal.
 * Started from a terminal, it first re-launches itself as its own responsible process (the same trick
 * Chrome and Xcode use), so the permissions still belong to Lazy-Monster and not to Terminal. */
#include <dlfcn.h>
#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;
static pid_t child = 0;
static void fwd(int s) { if (child > 0) kill(child, s); }

static int run(char *path, char **argv, int disclaim) {
    posix_spawnattr_t at; posix_spawnattr_init(&at);
    if (disclaim) {
        int (*f)(posix_spawnattr_t *, int) = (int (*)(posix_spawnattr_t *, int))dlsym(RTLD_DEFAULT, "responsibility_spawnattrs_setdisclaim");
        if (f) f(&at, 1);
    }
    int rc = posix_spawn(&child, path, NULL, &at, argv, environ);
    posix_spawnattr_destroy(&at);
    if (rc != 0) { fprintf(stderr, "Lazy-Monster: could not start %s (error %d)\n", path, rc); return 127; }
    signal(SIGTERM, fwd); signal(SIGHUP, fwd);
    int st = 0;
    while (waitpid(child, &st, 0) < 0) {}
    return WIFEXITED(st) ? WEXITSTATUS(st) : 128 + WTERMSIG(st);
}

int main(int argc, char **argv) {
    char raw[PATH_MAX]; uint32_t n = sizeof raw;
    if (_NSGetExecutablePath(raw, &n) != 0) return 1;
    char exe[PATH_MAX]; if (!realpath(raw, exe)) strcpy(exe, raw);

    if (!getenv("LM_BUNDLE")) {                 /* step 1: become our own responsible app */
        setenv("LM_BUNDLE", "1", 1);
        char **a = calloc(argc + 1, sizeof *a);
        a[0] = exe; for (int i = 1; i < argc; i++) a[i] = argv[i];
        return run(exe, a, 1);
    }

    char tmp[PATH_MAX]; strcpy(tmp, exe);
    char *contents = dirname(dirname(tmp));      /* .../Lazy-Monster.app/Contents */
    char cfg[PATH_MAX]; snprintf(cfg, sizeof cfg, "%s/Resources/python-path", contents);
    char py[PATH_MAX] = "";
    FILE *f = fopen(cfg, "r");
    if (f) { if (fgets(py, sizeof py, f)) py[strcspn(py, "\r\n")] = 0; fclose(f); }
    if (!py[0]) snprintf(py, sizeof py, "%s/.lazymonster/app/.venv/bin/python", getenv("HOME") ? getenv("HOME") : "");
    char app[PATH_MAX]; strcpy(tmp, contents); snprintf(app, sizeof app, "%s", dirname(tmp));
    setenv("LM_APP_BUNDLE", app, 1);

    int extra = argc > 1 ? argc - 1 : 1;
    char **a = calloc(extra + 4, sizeof *a);
    a[0] = py; a[1] = "-m"; a[2] = "lazymonster.cli";
    if (argc > 1) for (int i = 1; i < argc; i++) a[2 + i] = argv[i];
    else a[3] = "ui";                            /* double-clicked in Finder: open the window */
    return run(py, a, 0);
}
