import json
import os
from pathlib import Path
import asyncio
import sqlite3
from contextlib import contextmanager


CREDENTIALS_FILE = "credentials.data"
MANIFEST = 'src/manifest.json'


class RpcChannel:
    def __init__(self, reader, writer, manifest):
        self._reader = reader
        self._writer = writer
        self._manifest = manifest
        self._id = 0

    async def __call__(self, method, params=None, use_id=True):
        print(f'calling {method} {params}')
        msg = {
            "jsonrpc": "2.0",
            "method": method
        }
        if use_id:
            self._id += 1
            msg['id'] = self._id
        if params is not None:
            msg['params'] = params

        encoded = json.dumps(msg).encode() + b"\n"
        self._writer.write(encoded)
        await self._writer.drain()
        try:
            response = await self._reader.readline()
            print("ret", response)
        except ValueError:
            # response line too long ("Separator is found, but chunk is longer than limit" by wrreadline())
            return
        return response

    @contextmanager
    def _local_storage(self):
        """Warning: in case multiple GOG users, choses plugin database at random"""
        indentifier = f"{self._manifest['platform']}_{self._manifest['guid']}"
        local_storage_path = os.path.expandvars(f"%programdata%/GOG.com/Galaxy/storage/plugins")
        databases = os.listdir(local_storage_path)
        for db_name in databases:
            if indentifier in db_name:
                db_path = os.path.join(local_storage_path, db_name)
                break
        else:
            raise RuntimeError(f'No local database with {indentifier} found in {local_storage_path}')
        connection = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
        try:
            yield connection.cursor()
        finally:
            connection.close()

    async def _send_notification(self, name, params):
        await self.__call__(name, params, use_id=False)

    async def _send_request(self, name, params):
        await self.__call__(name, params, use_id=True)

    async def install_game(self, game_id):
        await self._send_notification('install_game', {'game_id': game_id})

    async def launch_game(self, game_id):
        await self._send_notification('launch_game', {'game_id': game_id})

    async def uninstall_game(self, game_id):
        await self._send_notification('uninstall_game', {'game_id': game_id})

    async def initialize_cache(self, data=None):
        """
        :param data: if None, local database storage will be used
        """
        if data == None:
            with self._local_storage() as cursor:
                key_value_cursor = cursor.execute("SELECT * FROM KeyValueStorage")
                data  = {}
                for key, value in key_value_cursor:
                    data[key.decode()] = value.decode()
        await self._send_request('initialize_cache', {'data': data})


if __name__ == "__main__":

    async def run_server_connection(reader, writer):

        with open(MANIFEST, 'r') as f:
            manifest = json.load(f)

        path = Path(CREDENTIALS_FILE)
        if not path.exists():
            path.touch()

        galaxy_rpc = RpcChannel(reader, writer, manifest)

        with open(CREDENTIALS_FILE, "r") as f:
            data = f.read()
            if data:
                credentials = json.loads(data)
            else:
                raise RuntimeError('No credentials found')

        await galaxy_rpc.initialize_cache()
        await galaxy_rpc('init_authentication', {"stored_credentials": credentials})
        await galaxy_rpc('import_owned_games')
        # await galaxy_rpc('import_local_games')
        # await galaxy_rpc.install_game("annasquest_trove")
        # await galaxy_rpc.launch_game("annasquest_trove")
        # await galaxy_rpc.uninstall_game("annasquest_trove")

    async def start_test():
        await asyncio.start_server(run_server_connection, "127.0.0.1", "7994")

    loop = asyncio.get_event_loop()
    loop.create_task(start_test())
    loop.run_forever()
