import asyncio
from redis.asyncio import Redis
from config import Database
from typing import List, Union

class RedisClient:
    def __init__(self, host: str, port: int, password: str):
        self.db = Redis(
            host=host,
            port=port,
            password=password,
            ssl=True,
            decode_responses=True
        )

    def _s_l(self, text: str) -> List[str]:
        return text.split(" ")

    def _l_s(self, lst: List[str]) -> str:
        return " ".join(lst).strip()

    def _ensure_str(self, value: Union[str, int]) -> str:
        return str(value)

    async def is_inserted(self, var: Union[str, int], id: Union[str, int]) -> bool:
        try:
            users = await self.fetch_all(self._ensure_str(var))
            return self._ensure_str(id) in users
        except Exception:
            return False

    async def insert(self, var: Union[str, int], id: Union[str, int]) -> bool:
        try:
            var_str = self._ensure_str(var)
            id_str = self._ensure_str(id)
            users = await self.fetch_all(var_str)
            if id_str not in users:
                users.append(id_str)
                await self.db.set(var_str, self._l_s(users))
            return True
        except Exception:
            return False

    async def fetch_all(self, var: str) -> List[str]:
        try:
            users = await self.db.get(var)
            return [] if users is None or users == "" else self._s_l(users)
        except Exception:
            return []

    async def delete(self, var: Union[str, int], id: Union[str, int]) -> bool:
        try:
            var_str = self._ensure_str(var)
            id_str = self._ensure_str(id)
            users = await self.fetch_all(var_str)
            if id_str in users:
                users.remove(id_str)
                await self.db.set(var_str, self._l_s(users))
            return True
        except Exception:
            return False

db = RedisClient(Database.REDIS_HOST, Database.REDIS_PORT, Database.REDIS_PASSWORD)
