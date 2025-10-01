import time
import requests
from collections import defaultdict
from typing import Dict, List, Callable, Iterable, Optional, Tuple, Any
from colorama import Fore, Style
from Basketball.Logger.statsResults import ResultLogger


class TotalBoxScorePlayer:
    """
        # STEPS TO USE THE SCRIPT:\n
        **game uuid**: b1cl5bm0hs7uu7e8rn02h8hzo, **playerId**: 5a26i35oyvyj8xpo9kr86mmeh \n
        **1. Load the game** in: https://api.performfeeds.com/basketballdata/matchevent/mcp6s4o523yuz4q2i7bcv9c6/16bb2d6s6b67lotm8q2cmj504?_rt=b&_fmt=xml \n
        **2. Get the date of the game and go to optaLive**: https://live.opta.statsperform.com/basketball , select the date ond the league to narrow down the search \n
        **3. Find the game and click on the game** - look for the gameId: 2694505 (it's also in the link) \n
        **4. Use the gameId in this script** to verify the results \n
        \n
        # NOTES:\n
        **gameId:** 2693599 \n
        **gameUUID:** 16bb2d6s6b67lotm8q2cmj504\n
        Stats Endpoint: `https://prod.origin.api.stats.com/v1/stats/basketball/NBA/events/2693599?pbp=true&accept=json` \n
        Performfeeds: https://api.performfeeds.com/basketballdata/matchevent/mcp6s4o523yuz4q2i7bcv9c6/16bb2d6s6b67lotm8q2cmj504?_rt=b&_fmt=xml \n

        **PLAYER TOTAL BOXSCORES ACHIEVED HERE:** \n
        - TotalFreeThrowsMade \n
        - TotalFieldGoalsMade \n
        - TotalThreePointsMade \n
        - TotalThreePointAttemptsMade \n
        - TotalAssistsMade \n
        - TotalReboundsMade \n
        - TotalBlocksMade \n
        - TotalStealsMade \n
        - TotalTurnoversMade \n
        - TotalPointsMade \n
        """

    STAT_LABELS: Dict[str, str] = {
        'playEventId_1': 'Free Throw Made',
        'playEventId_2': 'Free Throw Missed',
        'playEventId_3': 'Field Goal Made',
        'playEventId_4': 'Field Goal Missed',
        'playEventId_5': 'Offensive Rebound',
        'playEventId_6': 'Defensive Rebound',
        'playEventId_7': 'Turnover',
        'playEventId_8': 'Foul',
        'playEventId_9': 'Violation',
        'playEventId_10': 'Substitution',
        'playEventId_11': 'Timeout',
        'playEventId_12': 'Jump Ball',
        'playEventId_14': 'Start Period',
        'playEventId_15': 'End Period',
        'playEventId_19': 'Game Over',
    }

    #  Rules for totals (what can be passed in STAT_KEYS)
    TOTAL_DEFS: Dict[str, str] = {
        'TotalPointsMade': 'TOTAL_POINTS',              # FTM (1) +1; FGM (3) +points (or +3 if 3PT else +2)
        'TotalThreePointsMade': 'TOTAL_TPM',            # FGM (3) with 3PT attempt → +1
        'TotalThreePointAttemptsMade': 'TOTAL_TPAM',    # FGM (3) or FGMiss (4) with 3PT attempt → +1
        'TotalFieldGoalsMade': 'TOTAL_FGM',             # FGM (3) → +1
        'TotalFreeThrowsMade': 'TOTAL_FFM',             # FTM (1) → +1
        'TotalAssistsMade': 'TOTAL_AM',                 # FGM (3) with assistPlayerId → assister +1
        'TotalReboundsMade': 'TOTAL_RM',                # OREB (5) or DREB (6) → rebounder +1
        'TotalBlocksMade': 'TOTAL_BM',                  # FGMiss (4) with blockPlayerId → blocker +1
        'TotalStealsMade': 'TOTAL_SM',                  # Turnover (7) with stealPlayerId → stealer +1
        'TotalTurnoversMade': 'TOTAL_TM',               # Turnover (7) → turnover committer (primary actor) +1
    }

    def __init__(self, *, base_url: str, logger: Optional[ResultLogger] = None, timeout: int = 20):
        self.base_url = base_url.rstrip('/')
        self.logger = logger
        self.timeout = timeout

    # =========================
    # TOTALS PER PLAYER:
    # =========================
    def process_games_totals(
        self,
        game_ids: Iterable[int],
        stat_keys: Iterable[str],
        player_ids: Iterable[int],
    ) -> Dict[int, Dict[str, Dict[str, int]]]:

        if isinstance(stat_keys, (str,)):
            stat_keys = [s.strip() for s in str(stat_keys).split(',') if s.strip()]
        keys = [k for k in stat_keys if k in self.TOTAL_DEFS]
        players = {str(int(pid)) for pid in player_ids}

        results: Dict[int, Dict[str, Dict[str, int]]] = {}

        for game_id in game_ids:
            if self.logger:
                self.logger.log_section(f"Processing game {game_id} | keys={keys} | players={sorted(players)}")

            data = self._fetch_game(game_id)
            if not data:
                results[game_id] = {}
                if self.logger:
                    self.logger.log_line(f"[WARN] No data for game {game_id}")
                continue

            pbp = self._extract_pbp(data, game_id)
            if not isinstance(pbp, list) or not pbp:
                results[game_id] = {}
                if self.logger:
                    self.logger.log_line(f"[WARN] No PBP found for game {game_id}.")
                continue

            calculators = self._build_calculators(keys)

            totals: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
            for play in pbp:
                increments: List[Tuple[str, str, int]] = []
                for calc in calculators:
                    increments.extend(calc(play))
                if not increments:
                    continue
                for pid, key, delta in increments:
                    if pid in players:
                        totals[pid][key] += delta

            results[game_id] = {pid: dict(kv) for pid, kv in totals.items()}
            self._print_totals_table(game_id, totals, keys)

        return results

    # =========================
    # Calculators for totals
    # =========================
    def _build_calculators(self, stat_keys: Iterable[str]) -> List[Callable[[Dict[str, Any]], List[Tuple[str, str, int]]]]:
        calcs: List[Callable[[Dict[str, Any]], List[Tuple[str, str, int]]]] = []
        for key in stat_keys:
            kind = self.TOTAL_DEFS.get(key)
            if not kind:
                continue
            if kind == 'TOTAL_POINTS':
                calcs.append(self._calc_total_points(key))
            elif kind == 'TOTAL_TPM':
                calcs.append(self._calc_three_points_made(key))
            elif kind == 'TOTAL_TPAM':
                calcs.append(self._calc_three_point_attempts(key))
            elif kind == 'TOTAL_FGM':
                calcs.append(self._calc_field_goals_made(key))
            elif kind == 'TOTAL_FFM':
                calcs.append(self._calc_free_throws_made(key))
            elif kind == 'TOTAL_AM':
                calcs.append(self._calc_assists(key))
            elif kind == 'TOTAL_RM':
                calcs.append(self._calc_rebounds(key))
            elif kind == 'TOTAL_BM':
                calcs.append(self._calc_blocks(key))
            elif kind == 'TOTAL_SM':
                calcs.append(self._calc_steals(key))
            elif kind == 'TOTAL_TM':
                calcs.append(self._calc_turnovers(key))
        return calcs

    # --- individual calculators ---
    def _calc_free_throws_made(self, key_name: str):
        # FTM: playEventId == 1 → shooter +1
        def f(play: Dict[str, Any]):
            if self._event_id(play) != 1:
                return []
            shooter = self._primary_actor(play)
            return [(shooter, key_name, 1)] if shooter else []
        return f

    def _calc_field_goals_made(self, key_name: str):
        # FGM: playEventId == 3 → shooter +1
        def f(play: Dict[str, Any]):
            if self._event_id(play) != 3:
                return []
            shooter = self._primary_actor(play)
            return [(shooter, key_name, 1)] if shooter else []
        return f

    def _calc_three_points_made(self, key_name: str):
        # 3PM: count only made field goals that scored 3 points
        def f(play: Dict[str, Any]):
            if self._event_id(play) != 3:
                return []
            pts = play.get('pointsScored')
            try:
                pts = int(pts)
            except (TypeError, ValueError):
                return []
            if pts != 3:
                return []
            shooter = self._primary_actor(play)
            return [(shooter, key_name, 1)] if shooter else []

        return f

    def _calc_three_point_attempts(self, key_name: str):
        # 3PA: any 3-pt field-goal attempt (made or missed)
        # i.e., playEventId in {3 (FGM), 4 (FGMiss)} AND shotAttemptPoints == 3
        def f(play: Dict[str, Any]):
            eid = self._event_id(play)
            if eid not in (3, 4):
                return []

            # top-level shotAttemptPoints
            sap = play.get('shotAttemptPoints')
            is_three = None
            if sap is not None:
                try:
                    is_three = (int(sap) == 3)
                except (TypeError, ValueError):
                    is_three = None

            # Fallback to detail flags if needed
            if is_three is None:
                is_three = self._is_three_attempt(play)

            if not is_three:
                return []

            shooter = self._primary_actor(play)
            return [(shooter, key_name, 1)] if shooter else []

        return f

    def _calc_assists(self, key_name: str):
        # AST: FGM (playEventId == 3) and players[sequence==2] is the assister → +1 to that player
        def f(play: Dict[str, Any]):
            if self._event_id(play) != 3:
                return []
            players = play.get('players') or []
            if not isinstance(players, list) or len(players) < 2:
                return []

            assister = next((p for p in players if p.get('sequence') == 2), None)
            if assister is None:
                if len(players) >= 2:
                    assister = players[1]  # fallback
                else:
                    return []
            apid = assister.get('playerId')
            if apid is None:
                return []
            return [(self._to_str(apid), key_name, 1)]

        return f

    def _calc_rebounds(self, key_name: str):
        # REB: OREB (5) or DREB (6) → +1 to rebounder (primary actor)
        def f(play: Dict[str, Any]):
            if self._event_id(play) not in (5, 6):
                return []
            reb = self._primary_actor(play)
            return [(reb, key_name, 1)] if reb else []
        return f

    def _calc_blocks(self, key_name: str):
        # BLK: Field Goal Missed (playEventId == 4) AND isBlocked == True
        # Blocker is the second involved player in `players` (sequence==2 if present; else players[1])
        def f(play: Dict[str, Any]):
            if self._event_id(play) != 4:
                return []
            if not play.get('isBlocked', False):
                return []

            players = play.get('players') or []
            if not isinstance(players, list) or len(players) < 2:
                return []

            blocker = next((p for p in players if p.get('sequence') == 2), None)
            if blocker is None:
                blocker = players[1]

            bpid = blocker.get('playerId')
            if bpid is None:
                return []
            return [(self._to_str(bpid), key_name, 1)]

        return f

    def _calc_steals(self, key_name: str):
        # STL: Turnover (playEventId == 7), stealer is the second involved player.
        # Prefer players[sequence == 2]; fallback to the second entry in players[].
        def f(play: Dict[str, Any]):
            if self._event_id(play) != 7:
                return []
            players = play.get('players') or []
            if not isinstance(players, list) or len(players) < 2:
                return []

            stealer = next((p for p in players if p.get('sequence') == 2), None)
            if stealer is None:
                stealer = players[1]

            spid = stealer.get('playerId')
            if spid is None:
                return []
            return [(self._to_str(spid), key_name, 1)]

        return f

    def _calc_turnovers(self, key_name: str):
        # TOV: Turnover (7) → +1 to turnover committer (primary actor)
        def f(play: Dict[str, Any]):
            if self._event_id(play) != 7:
                return []
            actor = self._primary_actor(play)
            return [(actor, key_name, 1)] if actor else []
        return f

    def _calc_total_points(self, key_name: str):
        # POINTS (actual): add top-level pointsScored to the shooter only when > 0.
        # No inference from 3PT flags or shotAttemptPoints.
        def f(play: Dict[str, Any]):
            pts = play.get('pointsScored')
            try:
                pts = int(pts) if pts is not None else 0
            except (TypeError, ValueError):
                pts = 0
            if pts <= 0:
                return []

            actor = self._primary_actor(play)
            if not actor:
                return []

            return [(actor, key_name, pts)]

        return f

    # =========================
    # Utilities & parsing
    # =========================
    def _fetch_game(self, game_id: int) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}/{game_id}?pbp=true&accept=json"
        if self.logger:
            self.logger.log_line(f"GET {url}")
        try:
            r = requests.get(url, timeout=self.timeout)
        except Exception as e:
            if self.logger:
                self.logger.log_line(f"[ERROR] Request failed for game {game_id}: {e}")
            return None
        if r.status_code != 200:
            if self.logger:
                self.logger.log_line(f"[HTTP {r.status_code}] Failed to fetch game {game_id}")
            return None
        try:
            return r.json()
        except Exception:
            if self.logger:
                self.logger.log_line(f"Invalid JSON in response for game {game_id}")
            return None

    def _extract_pbp(self, data: Dict[str, Any], game_id: Optional[int] = None) -> List[Dict[str, Any]]:
        pbp = data.get('pbp')
        if isinstance(pbp, list) and pbp:
            return pbp
        api_results = data.get('apiResults') or []
        for res in api_results:
            league = res.get('league') or {}
            season = league.get('season') or {}
            event_types = season.get('eventType') or []
            for et in event_types:
                events = et.get('events') or []
                for ev in events:
                    if game_id is not None:
                        try:
                            if int(ev.get('eventId')) != int(game_id):
                                continue
                        except (TypeError, ValueError):
                            pass
                    ev_pbp = ev.get('pbp')
                    if isinstance(ev_pbp, list) and ev_pbp:
                        return ev_pbp
        return []

    def _event_id(self, play: Dict[str, Any]) -> Optional[int]:
        pe = (play.get('playEvent') or {})
        try:
            return int(pe.get('playEventId'))
        except (TypeError, ValueError):
            return None

    def _primary_actor(self, play: Dict[str, Any]) -> Optional[str]:
        # Prefer players[sequence==1], fallback to first, else detail fields
        players = play.get('players') or []
        if isinstance(players, list) and players:
            seq1 = next((p for p in players if p.get('sequence') == 1), None)
            pid = (seq1 or players[0]).get('playerId')
            if pid is not None:
                return str(pid)
        d = (play.get('playEvent') or {}).get('playDetail') or {}
        cand = d.get('playerId') or d.get('shooterPlayerId') or d.get('rebounderPlayerId')
        return str(cand) if cand is not None else None

    def _is_three_attempt(self, play: Dict[str, Any]) -> bool:
        d = (play.get('playEvent') or {}).get('playDetail') or {}
        spts = d.get('shotAttemptPoints')
        if spts is not None:
            try:
                return int(spts) == 3
            except (TypeError, ValueError):
                pass

        for f in (d.get('isThreePoint'), d.get('threePoint'), d.get('is3pt')):
            if isinstance(f, bool) and f:
                return True
            if f in (1, "1", "true", "True"):
                return True
        pts = d.get('points')
        try:
            if int(pts) == 3:
                return True
        except (TypeError, ValueError):
            pass
        return False

    def _to_str(self, x: Any) -> Optional[str]:
        try:
            return str(int(x))
        except (TypeError, ValueError):
            return str(x) if x is not None else None

    # =========================
    # Console Printing
    # =========================
    def _print_totals_table(self, game_id: int, totals: Dict[str, Dict[str, int]], stat_keys: List[str]) -> None:
        if not self.logger:
            return
        line = "—" * 300
        self.logger.log_line(Fore.CYAN + line + Style.RESET_ALL)
        header = f"{'GameId':<10} {'PlayerId':<12} " + " ".join([f"{k:<26}" for k in stat_keys])
        self.logger.log_line(header)
        self.logger.log_line(line)
        for pid in sorted(totals.keys(), key=lambda x: int(x)):
            row = f"{game_id:<10} {pid:<12} " + " ".join([f"{totals[pid].get(k, 0):<26}" for k in stat_keys])
            self.logger.log_line(row)
        self.logger.log_line(Fore.CYAN + line + Style.RESET_ALL)


if __name__ == '__main__':
    # Params: flexible, accept multiple keys, games, and players
    BASE_URL = "https://prod.origin.api.stats.com/v1/stats/basketball/NBA/events"
    STAT_KEYS = [
        'TotalFreeThrowsMade',
        'TotalFieldGoalsMade',
        'TotalThreePointsMade',
        'TotalThreePointAttemptsMade',
        'TotalAssistsMade',
        'TotalReboundsMade',
        'TotalBlocksMade',
        'TotalStealsMade',
        'TotalTurnoversMade',
        'TotalPointsMade',
    ]
    GAMES = [2693599]       # one or many
    PLAYER_IDS = [214152]   # one or many

    logger = ResultLogger(stat_key=",".join(STAT_KEYS), stat_labels=TotalBoxScorePlayer.STAT_LABELS)

    overall_start = time.time()
    tracker = TotalBoxScorePlayer(base_url=BASE_URL, logger=logger)
    results = tracker.process_games_totals(GAMES, STAT_KEYS, PLAYER_IDS)

    elapsed = time.time() - overall_start
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    line = "—" * 300
    centered = f"Total run time: {minutes} min {seconds} sec".center(255)
    print(f"{Fore.CYAN}{line}\n{centered}\n{line}{Style.RESET_ALL}")
