"""Apply resource limits to a child command. This is NOT a security sandbox."""

import os
import resource
import sys


def main() -> None:
    seconds, memory_mb, file_mb = (int(value) for value in sys.argv[1:4])
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds + 1))
    resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024**2,) * 2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_mb * 1024**2,) * 2)
    os.execv(sys.argv[4], sys.argv[4:])


if __name__ == "__main__":
    main()
