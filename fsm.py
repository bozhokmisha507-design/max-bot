from typing import Dict, Any, Optional


class FSM:
    def __init__(self):
        self._data: Dict[int, Dict[str, Any]] = {}

    def get(self, user_id: int) -> Dict[str, Any]:
        return self._data.setdefault(user_id, {})

    def state(self, user_id: int) -> Optional[str]:
        return self.get(user_id).get("state")

    def set_state(self, user_id: int, state: Optional[str]):
        self.get(user_id)["state"] = state

    def update(self, user_id: int, **kwargs):
        self.get(user_id).update(kwargs)

    def clear(self, user_id: int):
        self._data.pop(user_id, None)


fsm = FSM()