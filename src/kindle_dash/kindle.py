import asyncio

BEDTIME_COMMAND = "/var/local/kindle-dash/night.sh bedtime"
TIMEOUT_SECONDS = 10


class KindleError(Exception):
    pass


async def bedtime(ssh_host: str) -> None:
    """Asks the Kindle to sleep until its usual wake-up time."""
    ssh = await asyncio.create_subprocess_exec(
        *("/usr/bin/ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"),
        *(ssh_host, BEDTIME_COMMAND),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(ssh.communicate(), TIMEOUT_SECONDS)
    except TimeoutError as e:
        ssh.kill()
        await ssh.wait()
        raise KindleError(f"no answer within {TIMEOUT_SECONDS} seconds") from e
    if ssh.returncode != 0:
        raise KindleError(f"ssh exited {ssh.returncode}: {stderr.decode().strip()}")
