import growattServer
import logging
import time as time_module
from datetime import date
from ..config import GrowattConfig, RatesConfig

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class GrowattError(Exception):
    pass


class GrowattClient:
    def __init__(self, config: GrowattConfig, rates: RatesConfig):
        self.config = config
        self.rates = rates
        self._api = growattServer.GrowattApi()
        self._api.session.headers.update({"User-Agent": USER_AGENT})
        self._api.server_url = config.server_url
        self.logged_in = False

    def login(self) -> None:
        def _do_login():
            result = self._api.login(self.config.username, self.config.password)
            if not result.get("success"):
                raise GrowattError(f"Login failed: {result.get('error', 'unknown')}")
            return result
        self._retry(_do_login)
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
        def _do():
            raw = self._api.dashboard_data(
                self.config.plant_id, growattServer.Timespan.hour, target_date
            )
            return raw.get("chartData", {})
        return self._retry(_do)

    def get_current_soc(self) -> int:
        def _do():
            devices = self._api.device_list(self.config.plant_id)
            for dev in devices:
                if dev.get("deviceSn") == self.config.device_sn:
                    cap_str = dev.get("capacity", "0%").replace("%", "")
                    return int(cap_str)
            raise GrowattError(f"Device {self.config.device_sn} not found")
        return self._retry(_do)

    def _charge_periods(self) -> list[tuple[int, int, int, int]]:
        """Return up to 2 (start_h, start_m, end_h, end_m) ranges matching the
        configured cheap window. Windows wrapping midnight split at 23:59/00:00."""
        sh, sm = (int(x) for x in self.rates.cheap_start.split(":"))
        eh, em = (int(x) for x in self.rates.cheap_end.split(":"))
        if (sh, sm) == (eh, em):
            raise ValueError("cheap_start and cheap_end must differ")
        if (sh, sm) < (eh, em):
            return [(sh, sm, eh, em)]
        return [(sh, sm, 23, 59), (0, 0, eh, em)]

    def set_charge_soc(self, soc_pct: int) -> bool:
        soc_pct = max(0, min(100, soc_pct))
        periods = self._charge_periods()
        slot1 = periods[0]
        slot2 = periods[1] if len(periods) > 1 else (0, 0, 0, 0)
        slot1_on = "1"
        slot2_on = "1" if len(periods) > 1 else "0"

        def _fmt(n: int) -> str:
            return f"{n:02d}"

        def _do_set():
            resp = self._api.session.post(
                f"{self.config.server_url}tcpSet.do",
                data={
                    "action": "spaSet",
                    "serialNum": self.config.device_sn,
                    "type": "spa_ac_charge_time_period",
                    "param1": "100", "param2": str(soc_pct),
                    "param3": _fmt(slot1[0]), "param4": _fmt(slot1[1]),
                    "param5": _fmt(slot1[2]), "param6": _fmt(slot1[3]),
                    "param7": slot1_on,
                    "param8": _fmt(slot2[0]), "param9": _fmt(slot2[1]),
                    "param10": _fmt(slot2[2]), "param11": _fmt(slot2[3]),
                    "param12": slot2_on,
                    "param13": "00", "param14": "00",
                    "param15": "00", "param16": "00", "param17": "0",
                }
            )
            result = resp.json()
            if not result.get("success"):
                raise GrowattError(f"Set charge failed: {result.get('msg')}")
            return True
        return self._retry(_do_set)
