import time
import requests
from collections import defaultdict
from typing import Dict, List, Callable, Iterable, Optional, Tuple, Any
from colorama import Fore, Style
from Basketball.Logger.statsResults import ResultLogger


class DoubleDoubleTripleDoublePlayer:
    """
            # STEPS TO USE THE SCRIPT:\n
            **game uuid**: b1cl5bm0hs7uu7e8rn02h8hzo, **playerId**: 5a26i35oyvyj8xpo9kr86mmeh \n
            **1. Load the game** in: https://api.performfeeds.com/basketballdata/matchevent/mcp6s4o523yuz4q2i7bcv9c6/16bb2d6s6b67lotm8q2cmj504?_rt=b&_fmt=xml \n
            **2. Get the date of the game and go to optaLive**: https://live.opta.statsperform.com/basketball , select the date and the league to narrow down the search \n
            **3. Find the game and click on the game** - look for the gameId: 2694505 (it's also in the link) \n
            **4. Use the gameId in this script** to verify the results \n
            \n
            # NOTES:\n
            **gameId:** 2693599 \n
            **gameUUID:** 16bb2d6s6b67lotm8q2cmj504\n
            Stats Endpoint: `https://prod.origin.api.stats.com/v1/stats/basketball/NBA/events/2693599?pbp=true&accept=json` \n
            Performfeeds: https://api.performfeeds.com/basketballdata/matchevent/mcp6s4o523yuz4q2i7bcv9c6/16bb2d6s6b67lotm8q2cmj504?_rt=b&_fmt=xml \n

            **PLAYER DOUBLE ACHIEVEMENTS HERE:** \n
            - Double-double \n
            - Triple-double \n
            - Quadruple-double \n
            - Quintuple-double \n

            **PLAYER DOUBLE ACHIEVEMENTS EXPLAINED:** \n
            - Double-double: is where more than 10 is achieved in 2 categories  \n
            - Triple-double: is where more than 10 is achieved in 3 categories \n
            - Quadruple-double: is where more than 10 is achieved in 4 categories \n
            - Quintuple-double: is where more than 10 is achieved in 5 categories \n

            **Categories considered:** \n
            - Points \n
            - Rebounds \n
            - Assists \n
            - Steals \n
            - Blocks \n

            **Side Note:** \n
            Quadruple-doubles and Quintuple-doubles are extremely rare in basketball history. \n
            There have been no recorded instances of a Quintuple-double in professional basketball in the last 20 years. \n
            """

    STAT_LABELS: Dict[str, str] = {
        'playEventId_3': 'Field Goal Made',
        'playEventId_4': 'Field Goal Missed',
        'playEventId_5': 'Offensive Rebound',
        'playEventId_6': 'Defensive Rebound',
        'playEventId_7': 'Turnover',
    }

    #  Rules for totals (what can be passed in STAT_KEYS)
    TOTAL_DEFS: Dict[str, str] = {
        'TotalPointsMade': 'TOTAL_POINTS',  # FTM (1) +1; FGM (3) +points (or +3 if 3PT else +2)
        'TotalAssistsMade': 'TOTAL_AM',  # FGM (3) with assistPlayerId → assister +1
        'TotalReboundsMade': 'TOTAL_RM',  # OREB (5) or DREB (6) → rebounder +1
        'TotalBlocksMade': 'TOTAL_BM',  # FGMiss (4) with blockPlayerId → blocker +1
        'TotalStealsMade': 'TOTAL_SM',  # Turnover (7) with stealPlayerId → stealer +1
    }

    # Readable mapping for achievements
    _STAT_READABLE: Dict[str, str] = {
        'TotalPointsMade': 'points',
        'TotalReboundsMade': 'rebounds',
        'TotalAssistsMade': 'assists',
        'TotalStealsMade': 'steals',
        'TotalBlocksMade': 'blocks',
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

            player_names = self._build_player_name_index(data, pbp)

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

            self._print_achievements(game_id, results[game_id], player_names)

            self._print_totals_table(game_id, totals, keys, player_names)

        return results

    # =========================
    # Calculators for totals
    # =========================
    def _build_calculators(self, stat_keys: Iterable[str]) -> List[
        Callable[[Dict[str, Any]], List[Tuple[str, str, int]]]]:
        calcs: List[Callable[[Dict[str, Any]], List[Tuple[str, str, int]]]] = []
        for key in stat_keys:
            kind = self.TOTAL_DEFS.get(key)
            if not kind:
                continue
            if kind == 'TOTAL_POINTS':
                calcs.append(self._calc_total_points(key))
            elif kind == 'TOTAL_AM':
                calcs.append(self._calc_assists(key))
            elif kind == 'TOTAL_RM':
                calcs.append(self._calc_rebounds(key))
            elif kind == 'TOTAL_BM':
                calcs.append(self._calc_blocks(key))
            elif kind == 'TOTAL_SM':
                calcs.append(self._calc_steals(key))
        return calcs

    # --- individual calculators ---

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

    # ======================================================
    # Achievements (Double / Triple / Quadruple / Quintuple)
    # ======================================================
    def _collect_qualifying_categories(self, player_totals: Dict[str, int]) -> List[Tuple[str, int]]:
        qualifying: List[Tuple[str, int]] = []
        for key, readable in self._STAT_READABLE.items():
            val = int(player_totals.get(key, 0) or 0)
            if val >= 10:
                qualifying.append((readable, val))
        qualifying.sort(key=lambda x: (-x[1], x[0]))
        return qualifying

    def _format_combo(self, items: List[Tuple[str, int]]) -> str:
        # "25 points, 12 rebounds, 10 assists"
        return ", ".join(f"{v} {name}" for name, v in items)

    def _achievement_lines(self, player_totals: Dict[str, int]) -> List[str]:
        q = self._collect_qualifying_categories(player_totals)
        n = len(q)
        if n < 2:
            return []
        labels = {2: "Double-double", 3: "Triple-double", 4: "Quadruple-double", 5: "Quintuple-double"}
        return [f"{labels[level]}: {self._format_combo(q[:level])}" for level in range(2, min(n, 5) + 1)]

    def _print_achievements(self, game_id: int, totals: Dict[str, Dict[str, int]],
                            player_names: Dict[str, str]) -> None:
        if not self.logger:
            return

        width = 120
        rule_hard = "=" * width
        rule_soft = "-" * width

        self.logger.log_line(Fore.CYAN + rule_hard + Style.RESET_ALL)
        self.logger.log_line(Fore.CYAN + f"Game Summary: {game_id}" + Style.RESET_ALL)
        self.logger.log_line(rule_soft)
        self.logger.log_line(f"{'PlayerId':<12} {'PlayerName':<30} | Achievements")
        self.logger.log_line(rule_soft)

        any_line = False
        ordered_pids = sorted(totals.keys(), key=lambda x: int(x))
        for pid in ordered_pids:
            lines = self._achievement_lines(totals[pid])
            if not lines:
                continue
            any_line = True
            combined = "; ".join(lines)
            pname = player_names.get(pid, "")
            self.logger.log_line(f"{pid:<12} {pname:<30} | {combined}")

        if not any_line:
            self.logger.log_line("No double/triple/quadruple/quintuple achievements detected")

        self.logger.log_line(Fore.CYAN + rule_hard + Style.RESET_ALL)
        self.logger.log_line("")  # spacer

    # =========================
    # Player name extraction
    # =========================
    def _build_player_name_index(self, data: Dict[str, Any], pbp: List[Dict[str, Any]]) -> Dict[str, str]:
        name_map: Dict[str, str] = {}

        def add(pid, name):
            spid = self._to_str(pid)
            if not spid:
                return
            name = self._normalize_name(name)
            if name and spid not in name_map:
                name_map[spid] = name

        api_results = data.get('apiResults') or []
        for res in api_results:
            league = res.get('league') or {}
            season = league.get('season') or {}
            event_types = season.get('eventType') or []
            for et in event_types:
                events = et.get('events') or []
                for ev in events:
                    for team_key in ('teams', 'participants', 'competitors'):
                        teams = ev.get(team_key) or []
                        if isinstance(teams, dict):
                            teams = teams.get('team') or teams.get('competitor') or []
                        if not isinstance(teams, list):
                            continue
                        for t in teams:
                            for pkey in ('players', 'roster', 'athletes'):
                                players = t.get(pkey) or []
                                if isinstance(players, dict):
                                    players = players.get('player') or players.get('athlete') or []
                                if not isinstance(players, list):
                                    continue
                                for p in players:
                                    pid = p.get('playerId') or p.get('id')
                                    name = (
                                            p.get('displayName')
                                            or p.get('fullName')
                                            or " ".join(
                                        [str(p.get('firstName') or ""), str(p.get('lastName') or "")]).strip()
                                            or p.get('name')
                                    )
                                    add(pid, name)

        for team_key in ('teams', 'participants', 'competitors'):
            teams = data.get(team_key) or []
            if isinstance(teams, dict):
                teams = teams.get('team') or teams.get('competitor') or []
            if not isinstance(teams, list):
                continue
            for t in teams:
                for pkey in ('players', 'roster', 'athletes'):
                    players = t.get(pkey) or []
                    if isinstance(players, dict):
                        players = players.get('player') or players.get('athlete') or []
                    if not isinstance(players, list):
                        continue
                    for p in players:
                        pid = p.get('playerId') or p.get('id')
                        name = (
                                p.get('displayName')
                                or p.get('fullName')
                                or " ".join([str(p.get('firstName') or ""), str(p.get('lastName') or "")]).strip()
                                or p.get('name')
                        )
                        add(pid, name)

        for play in pbp:
            for pp in (play.get('players') or []):
                pid = pp.get('playerId')
                name = (
                        pp.get('playerName')
                        or pp.get('displayName')
                        or pp.get('fullName')
                        or " ".join([str(pp.get('firstName') or ""), str(pp.get('lastName') or "")]).strip()
                        or pp.get('name')
                )
                add(pid, name)

        return name_map

    def _normalize_name(self, s: Optional[str]) -> str:
        if not s:
            return ""
        return " ".join(str(s).split())

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
        players = play.get('players') or []
        if isinstance(players, list) and players:
            seq1 = next((p for p in players if p.get('sequence') == 1), None)
            pid = (seq1 or players[0]).get('playerId')
            if pid is not None:
                return str(pid)
        d = (play.get('playEvent') or {}).get('playDetail') or {}
        cand = d.get('playerId') or d.get('shooterPlayerId') or d.get('rebounderPlayerId')
        return str(cand) if cand is not None else None

    def _to_str(self, x: Any) -> Optional[str]:
        try:
            return str(int(x))
        except (TypeError, ValueError):
            return str(x) if x is not None else None

    # =========================
    # Console Printing
    # =========================
    def _print_achievements(self, game_id: int, totals: Dict[str, Dict[str, int]],
                            player_names: Dict[str, str]) -> None:
        if not self.logger:
            return

        width = 120
        rule_hard = "=" * width
        rule_soft = "-" * width

        self.logger.log_line(Fore.CYAN + rule_hard + Style.RESET_ALL)
        self.logger.log_line(Fore.CYAN + f"Game Summary: {game_id}" + Style.RESET_ALL)
        self.logger.log_line(rule_soft)
        self.logger.log_line(f"{'PlayerId':<12} {'PlayerName':<30} | Achievements")
        self.logger.log_line(rule_soft)

        any_line = False
        ordered_pids = sorted(totals.keys(), key=lambda x: int(x))
        for pid in ordered_pids:
            lines = self._achievement_lines(totals[pid])
            if not lines:
                continue
            any_line = True
            combined = "; ".join(lines)
            pname = player_names.get(pid, "")
            self.logger.log_line(f"{pid:<12} {pname:<30} | {combined}")

        if not any_line:
            self.logger.log_line("No double/triple/quadruple/quintuple achievements detected")

        self.logger.log_line(Fore.CYAN + rule_hard + Style.RESET_ALL)
        self.logger.log_line("")  # spacer

    def _print_totals_table(self, game_id: int, totals: Dict[str, Dict[str, int]], stat_keys: List[str],
                            player_names: Dict[str, str]) -> None:
        if not self.logger:
            return

        pretty = {
            'TotalAssistsMade': 'Assists',
            'TotalReboundsMade': 'Rebounds',
            'TotalBlocksMade': 'Blocks',
            'TotalStealsMade': 'Steals',
            'TotalPointsMade': 'Points',
        }
        headers = ["GameId", "PlayerId", "PlayerName"] + [pretty.get(k, k) for k in stat_keys]

        col_widths = {
            "GameId": 10,
            "PlayerId": 10,
            "PlayerName": 28,
        }
        default_width = 10
        for hdr in headers[3:]:
            col_widths[hdr] = max(default_width, len(hdr) + 1)

        def fmt_row(vals):
            parts = []
            parts.append(f"{vals[0]:<{col_widths['GameId']}}")
            parts.append(f"{vals[1]:<{col_widths['PlayerId']}}")
            parts.append(f"{vals[2]:<{col_widths['PlayerName']}}")
            for h, v in zip(headers[3:], vals[3:]):
                parts.append(f"{v:<{col_widths[h]}}")
            return "  ".join(parts)

        total_width = sum(col_widths[h] for h in headers) + 2 * (len(headers) - 1)
        rule_hard = "=" * total_width
        rule_soft = "-" * total_width

        self.logger.log_line("Player Totals")
        self.logger.log_line(Fore.CYAN + rule_hard + Style.RESET_ALL)

        self.logger.log_line(fmt_row(headers))
        self.logger.log_line(rule_soft)

        for pid in sorted(totals.keys(), key=lambda x: int(x)):
            row_vals = [str(game_id), str(pid), player_names.get(pid, "")]
            for k in stat_keys:
                row_vals.append(str(totals[pid].get(k, 0)))
            self.logger.log_line(fmt_row(row_vals))

        self.logger.log_line(Fore.CYAN + rule_hard + Style.RESET_ALL)
        self.logger.log_line("")


if __name__ == '__main__':
    BASE_URL = "https://prod.origin.api.stats.com/v1/stats/basketball/NBA/events"
    STAT_KEYS = [
        'TotalAssistsMade',
        'TotalReboundsMade',
        'TotalBlocksMade',
        'TotalStealsMade',
        'TotalPointsMade',
    ]
    GAMES = [2693599, 2694145, 2693976, 2694575]
    PLAYER_IDS = [214152, 830650, 739957]

    logger = ResultLogger(stat_key=",".join(STAT_KEYS), stat_labels=DoubleDoubleTripleDoublePlayer.STAT_LABELS)

    overall_start = time.time()
    tracker = DoubleDoubleTripleDoublePlayer(base_url=BASE_URL, logger=logger)
    results = tracker.process_games_totals(GAMES, STAT_KEYS, PLAYER_IDS)

    elapsed = time.time() - overall_start
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)

    width = 100
    rule = "=" * width
    print(rule)
    print(f"{'Total run time: ' + str(minutes) + ' min ' + str(seconds) + ' sec':^{width}}")
    print(rule)
