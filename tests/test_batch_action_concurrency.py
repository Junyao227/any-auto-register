import threading
import time
import unittest
from unittest import mock

from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

import api.actions as actions
from api.actions import BatchActionRequest, execute_batch_action
from core.db import AccountModel


class _SlowPlatform:
    """模拟一个慢动作平台，记录并发峰值。"""

    def __init__(self, *args, **kwargs):
        pass

    # 类级别共享计数，便于断言并发是否真正发生
    _lock = threading.Lock()
    _active = 0
    _peak = 0

    @classmethod
    def reset(cls):
        cls._active = 0
        cls._peak = 0

    def get_platform_actions(self):
        return [{"id": "relogin", "label": "重新登录", "params": []}]

    def execute_action(self, action_id, account, params):
        with _SlowPlatform._lock:
            _SlowPlatform._active += 1
            _SlowPlatform._peak = max(_SlowPlatform._peak, _SlowPlatform._active)
        try:
            time.sleep(0.2)  # 模拟收 OTP 的耗时
            return {
                "ok": True,
                "data": {"access_token": f"AT-{account.email}", "message": "重新登录成功"},
            }
        finally:
            with _SlowPlatform._lock:
                _SlowPlatform._active -= 1


class BatchActionConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        for i in range(1, 5):
            self.session.add(
                AccountModel(
                    platform="chatgpt",
                    email=f"user{i}@outlook.com",
                    password="pw",
                    user_id="",
                    token="old",
                    status="registered",
                    extra_json="{}",
                )
            )
        self.session.commit()
        _SlowPlatform.reset()

    def tearDown(self):
        self.session.close()

    def _call(self, concurrency):
        body = BatchActionRequest(
            account_ids=[1, 2, 3, 4],
            params={},
            concurrency=concurrency,
        )
        with mock.patch.object(actions, "_get_platform_cls_or_404", return_value=_SlowPlatform), \
            mock.patch.object(actions, "config_store") as cfg:
            cfg.get_all.return_value = {}
            return execute_batch_action("chatgpt", "relogin", body, session=self.session)

    def test_concurrent_batch_succeeds_for_all(self):
        result = self._call(concurrency=4)
        self.assertEqual(result["total"], 4)
        self.assertEqual(result["success"], 4)
        self.assertEqual(result["failed"], 0)
        # 并发度为 4 时，应观察到多个动作同时在执行
        self.assertGreater(_SlowPlatform._peak, 1)

    def test_results_written_back_to_db(self):
        self._call(concurrency=4)
        rows = self.session.exec  # ensure session usable
        acc = self.session.get(AccountModel, 1)
        self.assertEqual(acc.token, "AT-user1@outlook.com")

    def test_serial_when_concurrency_one(self):
        result = self._call(concurrency=1)
        self.assertEqual(result["success"], 4)
        # 串行执行时，峰值并发应为 1
        self.assertEqual(_SlowPlatform._peak, 1)

    def test_item_order_matches_input(self):
        result = self._call(concurrency=4)
        emails = [item["email"] for item in result["items"]]
        self.assertEqual(
            emails,
            ["user1@outlook.com", "user2@outlook.com", "user3@outlook.com", "user4@outlook.com"],
        )


if __name__ == "__main__":
    unittest.main()
