"""In a filter's own sandbox, where the host reaches it through a Unix socket only (Apple
container's --publish-socket): that socket, joined to the proxy's port on loopback. Mounted
into the filter, self-contained (the image has Python, not Handler).

    python3 front.py SOCKET PORT
"""

import asyncio
import contextlib
import os
import sys


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    with contextlib.suppress(OSError):
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
        if writer.can_write_eof():
            writer.write_eof()


async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, port: int) -> None:
    try:
        up_reader, up_writer = await asyncio.open_connection("127.0.0.1", port)
    except OSError:
        writer.close()
        return
    await asyncio.gather(pipe(reader, up_writer), pipe(up_reader, writer))
    writer.close()
    up_writer.close()


async def main(path: str, port: int) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)
    server = await asyncio.start_unix_server(lambda r, w: serve(r, w, port), path)
    os.chmod(path, 0o666)  # the host side may be another uid
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], int(sys.argv[2])))
