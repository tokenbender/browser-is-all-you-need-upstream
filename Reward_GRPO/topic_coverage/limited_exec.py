"""Apply resource limits to a child command. This is NOT a security sandbox."""

import os
import resource
import sys


def main() -> None:
    # Close-on-exec error channel: candidate stdout/exit codes cannot impersonate
    # launcher failures, and the executed candidate never inherits this fd.
    fd_text = os.environ.pop("TOPIC_LAUNCH_ERROR_FD", None)
    error_fd = int(fd_text) if fd_text is not None else None
    if error_fd is not None:
        os.set_inheritable(error_fd, False)
    try:
        seconds, memory_mb, file_mb = (int(value) for value in sys.argv[1:4])
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds + 1))
        resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024**2,) * 2)
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_mb * 1024**2,) * 2)
        os.execv(sys.argv[4], sys.argv[4:])
    except (OSError, ValueError) as error:
        detail = f"{type(error).__name__}: {error}"
        if error_fd is not None:
            os.write(error_fd, detail.encode("utf-8", errors="replace")[:4000])
        print(detail, file=sys.stderr)
        raise SystemExit(126)



if __name__ == "__main__":
    main()
