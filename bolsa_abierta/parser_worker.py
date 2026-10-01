"""One bounded parser process per new hash; the HTTP worker remains responsive."""
import json
import sys


def main():
    try:
        if sys.platform != 'win32':
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_CPU, (40, 40))
        from .parser import parse_pdf
        data = sys.stdin.buffer.read(10 * 1024 * 1024 + 1)
        result = parse_pdf(data, sys.argv[1], sys.argv[2])
        sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode())
    except Exception as exc:
        sys.stderr.write(str(exc)[:600])
        raise SystemExit(1)


if __name__ == '__main__':
    main()
