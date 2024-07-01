import subprocess


def _main():
    subprocess.run(["isort", "anxiousbot"], check=True)
    subprocess.run(["black", "anxiousbot"], check=True)


if __name__ == "__main__":
    _main()
