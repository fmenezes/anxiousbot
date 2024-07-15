import os
import subprocess


def _main():
    res = subprocess.run(
        ["poetry", "env", "info", "--path"], check=True, capture_output=True
    )
    cwd = os.path.abspath(os.path.join(res.stdout.decode("utf-8").strip("\n"), ".."))
    subprocess.run(["isort", "anxiousbot"], check=True, cwd=cwd)
    subprocess.run(["black", "anxiousbot"], check=True, cwd=cwd)


if __name__ == "__main__":
    _main()
