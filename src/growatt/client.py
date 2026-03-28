import growattServer
import logging
import time as time_module
from datetime import date
from ..config import GrowattConfig

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class GrowattError(Exception):
    pass


class GrowattClient:
    def __init__(self, config: GrowattConfig):
        self.config = config
        self._api = growattServer.GrowattApi()
        self._api.session.headers.update({"User-Agent": USER_AGENT})
        self._api.server_url = config.server_url
        self.logged_in = False

    def login(self) -> None:
        result = self._api.login(self.config.username, self.config.password)
        if not result.get("success"):
            raise GrowattError(f"Login failed: {result.get('error', 'unknown')}")
        self.logged_in = True
        logger.info("Growatt login successful")

    def _retry(self, func, retries=3, backoff=(5, 15, 45)):
        for attempt in range(retries):
            try:
                return func()
            except Exception as e:
                if attempt == retries - 1:
                    raise
                wait = backoff[attempt] if attempt < len(backoff) else backoff[-1]
                logger.warning(f"Attempt {attempt+1} failed: {e}. Retrying in {wait}s")
                time_module.sleep(wait)

    def get_hourly_data(self, target_date: date) -> dict:
        """Get 5-minute interval data for a day.
        Returns dict of time_str -> {ppv, sysOut, userLoad, pacToUser}
        where values are strings. 288 entries per full day.
        """
        raw = self._api.dashboard_data(
            self.config.plant_id, growattServer.Timespan.hour, target_date
        )
        return raw.get("chartData", {})

    def get_current_soc(self) -> int:
        devices = self._api.device_list(self.config.plant_id)
        for dev in devices:
            if dev.get("deviceSn") == self.config.device_sn:
                cap_str = dev.get("capacity", "0%").replace("%", "")
                return int(cap_str)
        raise GrowattError(f"Device {self.config.device_sn} not found")

    def set_charge_soc(self, soc_pct: int) -> bool:
        soc_pct = max(0, min(100, soc_pct))
        def _do_set():
            resp = self._api.session.post(
                f"{self.config.server_url}tcpSet.do",
                data={
                    "action": "spaSet",
                    "serialNum": self.config.device_sn,
                    "type": "spa_ac_charge_time_period",
                    "param1": "100", "param2": str(soc_pct),
                    "param3": "23", "param4": "30", "param5": "23", "param6": "59", "param7": "1",
                    "param8": "00", "param9": "00", "param10": "05", "param11": "30", "param12": "1",
                    "param13": "00", "param14": "00", "param15": "00", "param16": "00", "param17": "0",
                }
            )
            result = resp.json()
            if not result.get("success"):
                raise GrowattError(f"Set charge failed: {result.get('msg')}")
            return True
        return self._retry(_do_set)
