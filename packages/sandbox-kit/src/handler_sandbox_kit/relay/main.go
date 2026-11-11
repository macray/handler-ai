// handler-relay: the command of a sandbox on Apple container, whose networks do not isolate
// (apple/container#2062): a filtered sandbox has no network, only this relay to the host.
//
//	handler-relay [--user UID:GID] [--host /run/handler-host.sock \
//	    --listen tcp:127.42.0.1:3128=egress --listen unix:/run/handler-app/handler.sock=s0/handler.sock \
//	    --serve unix:/run/handler-app/app.sock=s0/app.sock] -- ARGV...
//
// With --user, started as root with CAP_SETUID, CAP_SETGID, CAP_SETPCAP and CAP_CHOWN only, it
// gives the host's socket to that user, empties the capability bounding set, sets
// no_new_privs (which Apple's `container` cannot) and becomes the user, before anything else.
//
// With --host, a sandbox with no network reaches the host through that one socket (Apple's
// `container run --volume <socket>:<path>`: each connect a new connection to it). Each listener
// gives the sandbox's programs an address leading to a target of the host: its network filter's
// proxy, handlerd's socket for an app. A program's connection becomes a new connection to the
// host's socket, which first says the target's name ("egress\n"), then carries the stream.
//
// The other way (--serve), a socket of the sandbox the host connects to: the host cannot connect
// into the VM (Apple refuses the Mac a socket made in a VM, apple/container#2101), so the relay
// waits on the host's side: `parked` connections to the host's socket, each saying "<NAME\n" and
// waiting. The host writes one byte on one when a client of its own connects; the relay joins it
// to that socket, here, and parks another in its place. Every connection is opened from here.
//
// It runs ARGV as its child once the listeners are up (stdio inherited) and, on a terminal, that
// terminal has its size; it passes signals on, and exits with its exit code. Linux only.
package main

import (
	"flag"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"
)

type listeners []string

func (l *listeners) String() string     { return strings.Join(*l, ",") }
func (l *listeners) Set(v string) error { *l = append(*l, v); return nil }

func main() {
	user := flag.String("user", "", "UID:GID to become (started as root)")
	host := flag.String("host", "", "the host's socket")
	var listen listeners
	flag.Var(&listen, "listen", "tcp:HOST:PORT=NAME or unix:PATH=NAME (repeatable, with --host)")
	var serves listeners
	flag.Var(&serves, "serve", "unix:PATH=NAME, the host reaching PATH as NAME (repeatable, with --host)")
	flag.Parse()
	if (len(listen) > 0 || len(serves) > 0) && *host == "" {
		fail("--listen and --serve need --host")
	}
	if flag.NArg() == 0 {
		fail("no command")
	}
	if *user != "" {
		become(*user, *host)
	}
	for _, spec := range listen {
		addr, name, ok := strings.Cut(spec, "=")
		network, address, ok2 := strings.Cut(addr, ":")
		if !ok || !ok2 || (network != "tcp" && network != "unix") {
			fail("bad --listen %q", spec)
		}
		if network == "unix" {
			os.Remove(address)
		}
		l, err := net.Listen(network, address)
		if err != nil {
			fail("listen %s: %v", spec, err)
		}
		go serve(l, *host, name)
	}
	for _, spec := range serves {
		addr, name, ok := strings.Cut(spec, "=")
		network, address, ok2 := strings.Cut(addr, ":")
		if !ok || !ok2 || network != "unix" {
			fail("bad --serve %q", spec)
		}
		for i := 0; i < parked; i++ {
			go park(*host, name, address)
		}
	}
	os.Exit(run(flag.Args()))
}

// parked: the connections waiting on the host's side for each served socket (the host keeps at
// most 4: more are closed); one taken is replaced at once.
const parked = 2

// park waits on the host's side for its clients, one at a time, for good: a connection to the
// host's socket ("<NAME\n"), then its byte, then the socket here joined to it.
func park(host, name, address string) {
	for {
		there, err := net.Dial("unix", host)
		if err == nil {
			_, err = fmt.Fprintf(there, "<%s\n", name)
		}
		var woken [1]byte
		if err == nil {
			_, err = io.ReadFull(there, woken[:])
		}
		if err != nil { // the host away (stopping), or this one closed: again, not in a loop
			if there != nil {
				there.Close()
			}
			time.Sleep(200 * time.Millisecond)
			continue
		}
		go func() {
			here, err := net.Dial("unix", address)
			if err != nil { // nothing listens yet: the host's client sees its connection end
				there.Close()
				return
			}
			join(here, there)
		}()
	}
}

// become gives the host's socket to uid:gid, then drops every privilege for good: the bounding
// set and no_new_privs on every thread (children inherit them), then the groups and ids.
func become(user, host string) {
	uidText, gidText, ok := strings.Cut(user, ":")
	uid, err1 := strconv.Atoi(uidText)
	gid, err2 := strconv.Atoi(gidText)
	if !ok || err1 != nil || err2 != nil {
		fail("bad --user %q", user)
	}
	if host != "" {
		if err := os.Chown(host, uid, gid); err != nil {
			fail("the host's socket: %v", err)
		}
	}
	for c := uintptr(0); c <= 63; c++ { // EINVAL past the kernel's last capability
		syscall.AllThreadsSyscall(syscall.SYS_PRCTL, prCapbsetDrop, c, 0)
	}
	if _, _, e := syscall.AllThreadsSyscall(syscall.SYS_PRCTL, prSetNoNewPrivs, 1, 0); e != 0 {
		fail("no_new_privs: %v", e)
	}
	if err := syscall.Setgroups(nil); err != nil {
		fail("groups: %v", err)
	}
	if err := syscall.Setresgid(gid, gid, gid); err != nil {
		fail("gid %d: %v", gid, err)
	}
	if err := syscall.Setresuid(uid, uid, uid); err != nil {
		fail("uid %d: %v", uid, err)
	}
}

const (
	prCapbsetDrop   = 24 // PR_CAPBSET_DROP
	prSetNoNewPrivs = 38 // PR_SET_NO_NEW_PRIVS
)

func serve(l net.Listener, host, name string) {
	for {
		c, err := l.Accept()
		if err != nil {
			fail("listener %s: %v", name, err)
		}
		go stream(c, host, name)
	}
}

func stream(c net.Conn, host, name string) {
	there, err := net.Dial("unix", host)
	if err != nil {
		c.Close()
		return
	}
	if _, err := fmt.Fprintf(there, "%s\n", name); err != nil {
		c.Close()
		there.Close()
		return
	}
	join(c, there)
}

type halfCloser interface{ CloseWrite() error }

// join copies both ways; each side's end is passed on as a half close.
func join(a, b net.Conn) {
	var wg sync.WaitGroup
	copyHalf := func(dst, src net.Conn) {
		defer wg.Done()
		io.Copy(dst, src)
		if h, ok := dst.(halfCloser); ok {
			h.CloseWrite()
		} else {
			dst.Close()
		}
	}
	wg.Add(2)
	go copyHalf(a, b)
	go copyHalf(b, a)
	wg.Wait()
	a.Close()
	b.Close()
}

// sizeWait: how long a terminal's process waits for its terminal's size, at most.
const sizeWait = 2 * time.Second

// waitForSize returns once stdin, a terminal, has a size (at once when it is not a terminal):
// Apple's `container start --attach` sizes the terminal just after the process starts, and a
// program asking its size at once (a full-screen one) would get 0x0.
func waitForSize() {
	var size struct{ rows, cols, x, y uint16 }
	deadline := time.Now().Add(sizeWait)
	for {
		_, _, errno := syscall.Syscall(
			syscall.SYS_IOCTL, 0, syscall.TIOCGWINSZ, uintptr(unsafe.Pointer(&size)))
		if errno != 0 || (size.rows > 0 && size.cols > 0) || time.Now().After(deadline) {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
}

// run starts argv, passes signals on, and returns its exit code (128+n when killed by signal n).
func run(argv []string) int {
	waitForSize()
	cmd := exec.Command(argv[0], argv[1:]...)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	// what the runtime sends (stopping the sandbox) is passed on; what a terminal sends (Ctrl-C,
	// a resize) already reaches the child, in the same process group: handled here (so the
	// child gets the default handling, not an inherited "ignore"), dropped
	passed := []os.Signal{syscall.SIGTERM, syscall.SIGHUP, syscall.SIGUSR1, syscall.SIGUSR2}
	dropped := []os.Signal{syscall.SIGINT, syscall.SIGQUIT, syscall.SIGWINCH, syscall.SIGTSTP}
	signals := make(chan os.Signal, 8)
	signal.Notify(signals, passed...)
	signal.Notify(make(chan os.Signal, 8), dropped...)
	if err := cmd.Start(); err != nil {
		fail("cannot start %s: %v", argv[0], err)
	}
	go func() {
		for s := range signals {
			cmd.Process.Signal(s)
		}
	}()
	err := cmd.Wait()
	if exit, ok := err.(*exec.ExitError); ok {
		if status, ok := exit.Sys().(syscall.WaitStatus); ok && status.Signaled() {
			return 128 + int(status.Signal())
		}
		return exit.ExitCode()
	}
	if err != nil {
		return 127
	}
	return 0
}

func fail(format string, args ...any) {
	fmt.Fprintf(os.Stderr, "handler-relay: "+format+"\n", args...)
	os.Exit(125)
}
