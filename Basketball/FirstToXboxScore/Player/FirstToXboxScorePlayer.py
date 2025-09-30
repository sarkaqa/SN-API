import time
import requests
from collections import defaultdict
from typing import Dict, List, Callable, Iterable, Optional, Tuple, Any
from colorama import Fore, Style
from Basketball.Logger.statsResults import ResultLogger

class FirstToXboxScorePlayer:

    """
    # STEPS TO USE THE SCRIPT:\n
    **game uuid**: b1cl5bm0hs7uu7e8rn02h8hzo, **playerId**: 5a26i35oyvyj8xpo9kr86mmeh \n
    **1. Load the game** in: https://api.performfeeds.com/basketballdata/matchstats/mcp6s4o523yuz4q2i7bcv9c6/b1cl5bm0hs7uu7e8rn02h8hzo?_rt=b&_fmt=xml \n
    **2. Get the date of the game and go to optaLive**: https://live.opta.statsperform.com/basketball?b1cl5bm0hs7uu7e8rn02h8hzo=&from=2025-03-07&to=2025-03-07 and select the date range ond the league \n
    **3. Find the game and click on the game** - look for the gameId: 2694505 (also it's in the link) \n
    **4. Use the gameId in this script** to verify the results \n
    \n
    # NOTES:\n
    Stats Endpoint: `https://prod.origin.api.stats.com/v1/stats/basketball/NBA/events/2694505?pbp=true&accept=json` \n

    **PLAYERS BOXSCORES ACHIEVED HERE:** \n
    - firstToXPoints (`scoredPoints`) \n
    - rebounds (`rebounds`) \n
    - field-goal attempts (`fieldGoalAttempts`) \n
    - free-throw attempts (`freeThrowAttempts`) \n
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

    COMPOSITE_DEFS: Dict[str, str] = {
        'scoredPoints': 'COMPOSITE_POINTS',
        'freeThrowAttempts': 'COMPOSITE_FTA',
        'fieldGoalAttempts': 'COMPOSITE_FGA',
        'rebounds': 'COMPOSITE_REB',
    }

    def __init__(self, *, base_url: str, logger: Optional[ResultLogger] = None, timeout: int = 20):
        self.base_url = base_url.rstrip('/')
        self.logger = logger
        self.timeout = timeout

    def process_games_first_to_threshold(
        self,
        game_ids: Iterable[int],
        stat_keys: Iterable[str],
        threshold: int,
    ) -> Dict[int, Optional[Dict[str, Any]]]:
        if isinstance(stat_keys, (str,)):
            stat_keys = [s.strip() for s in str(stat_keys).split(',') if s.strip()]
        results: Dict[int, Optional[Dict[str, Any]]] = {}
        for game_id in game_ids:
            if self.logger:
                self.logger.log_section(f"Processing game {game_id} | threshold={threshold} | keys={list(stat_keys)}")
            try:
                res = self._process_single_game_first_to_threshold(game_id, stat_keys, threshold)
                results[game_id] = res
                if res:
                    self._print_result(game_id, res)
                else:
                    if self.logger:
                        self.logger.log_line(f"No player reached threshold {threshold} for keys={list(stat_keys)} in game {game_id}.")
            except Exception as e:
                if self.logger:
                    self.logger.log_line(f"[ERROR] game {game_id}: {e}")
                results[game_id] = None
        return results

    def _process_single_game_first_to_threshold(
        self,
        game_id: int,
        stat_keys: Iterable[str],
        threshold: int,
    ) -> Optional[Dict[str, Any]]:
        data = self._fetch_game(game_id)
        if not data:
            return None
        roster = self._extract_roster_map(data)
        pbp = self._extract_pbp(data, game_id)
        if not isinstance(pbp, list) or not pbp:
            if self.logger:
                self.logger.log_line(f"No PBP found for game {game_id}.")
            return None

        incrementers = self._build_incrementers(stat_keys)
        totals: Dict[str, int] = defaultdict(int)
        first_hit: Optional[Tuple[str, int, str, Optional[int]]] = None
        hit_play: Optional[Dict[str, Any]] = None

        for play in pbp:
            deltas: List[Tuple[str, int]] = []
            for inc in incrementers:
                deltas.extend(inc(play))
            if not deltas:
                continue
            for pid, delta in deltas:
                if pid is None or delta is None:
                    continue
                totals[pid] += delta
                if totals[pid] >= threshold and first_hit is None:
                    play_id = str(play.get('playId')) if play.get('playId') is not None else None
                    team_id = play.get('teamId')
                    first_hit = (str(pid), totals[pid], play_id, team_id)
                    hit_play = play
                    break
            if first_hit:
                break

        if not first_hit:
            return None

        pid, value, play_id, team_id = first_hit
        name_info = self._resolve_player_name(pid, roster, pbp, hit_play or {})
        display = name_info.get('name') or name_info.get('displayName') or str(pid)
        return {
            'playerId': pid,
            'firstName': name_info.get('firstName', ''),
            'lastName': name_info.get('lastName', ''),
            'displayName': display,
            'name': display,
            'value': value,
            'playId': play_id,
            'teamId': team_id,
        }

    def _build_incrementers(self, stat_keys: Iterable[str]) -> List[Callable[[Dict[str, Any]], List[Tuple[str, int]]]]:
        incs: List[Callable[[Dict[str, Any]], List[Tuple[str, int]]]] = []
        for key in stat_keys:
            key = key.strip()
            if not key:
                continue
            if key in self.COMPOSITE_DEFS:
                kind = self.COMPOSITE_DEFS[key]
                if kind == 'COMPOSITE_POINTS':
                    incs.append(self._inc_scored_points())
                elif kind == 'COMPOSITE_FTA':
                    incs.append(self._inc_attempts(event_ids={1, 2}))
                elif kind == 'COMPOSITE_FGA':
                    incs.append(self._inc_attempts(event_ids={3, 4}))
                elif kind == 'COMPOSITE_REB':
                    incs.append(self._inc_rebounds())
                else:
                    incs.append(lambda play: [])
                continue
            if key.startswith('playEventId_'):
                try:
                    event_id = int(key.split('_', 1)[1])
                except ValueError:
                    event_id = None
                if event_id is None:
                    incs.append(lambda play: [])
                else:
                    incs.append(self._inc_by_event_id(event_id))
                continue
            try:
                event_id = int(key)
                incs.append(self._inc_by_event_id(event_id))
            except ValueError:
                incs.append(lambda play: [])
        return incs

    def _inc_by_event_id(self, event_id: int) -> Callable[[Dict[str, Any]], List[Tuple[str, int]]]:
        def f(play: Dict[str, Any]) -> List[Tuple[str, int]]:
            pe = (play.get('playEvent') or {})
            try:
                pid = int(pe.get('playEventId'))
            except (TypeError, ValueError):
                return []
            if pid != event_id:
                return []
            actor = self._get_primary_actor(play)
            return [(actor, 1)] if actor else []
        return f

    def _inc_attempts(self, *, event_ids: Iterable[int]) -> Callable[[Dict[str, Any]], List[Tuple[str, int]]]:
        ids = set(event_ids)
        def f(play: Dict[str, Any]) -> List[Tuple[str, int]]:
            pe = (play.get('playEvent') or {})
            try:
                pid = int(pe.get('playEventId'))
            except (TypeError, ValueError):
                return []
            if pid not in ids:
                return []
            player_id = self._get_primary_actor(play)
            return [(player_id, 1)] if player_id else []
        return f

    def _inc_rebounds(self) -> Callable[[Dict[str, Any]], List[Tuple[str, int]]]:
        ids = {5, 6}
        def f(play: Dict[str, Any]) -> List[Tuple[str, int]]:
            pe = (play.get('playEvent') or {})
            try:
                pid = int(pe.get('playEventId'))
            except (TypeError, ValueError):
                return []
            if pid not in ids:
                return []
            rebounder = self._get_primary_actor(play)
            return [(rebounder, 1)] if rebounder else []
        return f

    def _inc_scored_points(self) -> Callable[[Dict[str, Any]], List[Tuple[str, int]]]:
        def f(play: Dict[str, Any]) -> List[Tuple[str, int]]:
            pe = (play.get('playEvent') or {})
            try:
                pid = int(pe.get('playEventId'))
            except (TypeError, ValueError):
                return []
            actor = self._get_primary_actor(play)
            if not actor:
                return []
            if pid == 1:
                return [(actor, 1)]
            if pid == 3:
                detail = pe.get('playDetail') or {}
                pts = detail.get('points')
                if pts is None:
                    is_three = detail.get('isThreePoint') or detail.get('threePoint') or detail.get('is3pt')
                    pts = 3 if is_three else 2
                try:
                    pts = int(pts)
                except (TypeError, ValueError):
                    pts = 2
                return [(actor, pts)]
            return []
        return f

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

    def _extract_roster_map(self, data: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
        roster: Dict[str, Dict[str, str]] = {}
        league = data.get('league') or {}
        players = league.get('players') or []
        if isinstance(players, list):
            for p in players:
                pid = str(p.get('playerId') or p.get('id') or '')
                if not pid:
                    continue
                name = p.get('name') or p.get('displayName') or f"{p.get('firstName','')} {p.get('lastName','')}".strip()
                roster[pid] = {'name': name, 'firstName': p.get('firstName',''), 'lastName': p.get('lastName',''), 'displayName': name}
        if not roster:
            for res in data.get('apiResults', []):
                league = res.get('league') or {}
                season = league.get('season') or {}
                for et in season.get('eventType', []):
                    for ev in et.get('events', []):
                        for team in ev.get('teams', []):
                            for p in team.get('players', []):
                                pid = str(p.get('playerId') or p.get('id') or '')
                                if not pid:
                                    continue
                                name = p.get('name') or p.get('displayName') or f"{p.get('firstName','')} {p.get('lastName','')}".strip()
                                roster[pid] = {'name': name, 'firstName': p.get('firstName',''), 'lastName': p.get('lastName',''), 'displayName': name}
        return roster

    def _get_primary_actor(self, play: Dict[str, Any]) -> Optional[str]:
        players = play.get('players') or []
        if isinstance(players, list) and players:
            seq1 = next((p for p in players if p.get('sequence') == 1), None)
            pid = (seq1 or players[0]).get('playerId')
            if pid is not None:
                return str(pid)
        pe = (play.get('playEvent') or {})
        detail = pe.get('playDetail') or {}
        cand = detail.get('playerId') or detail.get('shooterPlayerId') or detail.get('rebounderPlayerId')
        if cand is not None:
            return str(cand)
        return None

    def _resolve_player_name(self, pid: str, roster: Dict[str, Dict[str, str]], pbp: list, play: dict) -> Dict[str, str]:
        for pl in (play.get('players') or []):
            if str(pl.get('playerId')) == str(pid):
                f = pl.get('firstName') or ''
                l = pl.get('lastName') or ''
                name = (pl.get('name') or f"{f} {l}".strip()) or str(pid)
                return {'name': name, 'firstName': f, 'lastName': l, 'displayName': name}
        if pid in roster:
            r = roster[pid]
            name = r.get('displayName') or r.get('name') or f"{r.get('firstName','')} {r.get('lastName','')}".strip() or str(pid)
            return {'name': name, 'firstName': r.get('firstName',''), 'lastName': r.get('lastName',''), 'displayName': name}
        for p in pbp:
            for pl in (p.get('players') or []):
                if str(pl.get('playerId')) == str(pid):
                    f = pl.get('firstName') or ''
                    l = pl.get('lastName') or ''
                    name = (pl.get('name') or f"{f} {l}".strip()) or str(pid)
                    return {'name': name, 'firstName': f, 'lastName': l, 'displayName': name}
        return {'name': str(pid), 'firstName': '', 'lastName': '', 'displayName': str(pid)}

    def _print_result(self, game_id: int, res: Dict[str, Any]) -> None:
        if not self.logger:
            return
        player_id = res.get('playerId', 'N/A')
        name = (res.get('name') or res.get('displayName') or f"{res.get('firstName','')} {res.get('lastName','')}".strip() or str(player_id))
        val = res.get('value', 'N/A')
        play_id = res.get('playId', 'N/A')
        team_id = res.get('teamId', 'N/A')
        line = (
            f"{Fore.CYAN}First to threshold for GameId:{Style.RESET_ALL} {game_id} ->  "
            f"{Fore.YELLOW}playerId:{Style.RESET_ALL} {player_id} | "
            f"{Fore.GREEN}player Name:{Style.RESET_ALL} {name} | "
            f"{Fore.MAGENTA}threshold value:{Style.RESET_ALL} {val} | "
            f"{Fore.BLUE}playId:{Style.RESET_ALL} {play_id} | "
            f"{Fore.CYAN}teamId:{Style.RESET_ALL} {team_id}"
        )
        self.logger.log_line(line)


if __name__ == '__main__':
    BASE_URL = "https://prod.origin.api.stats.com/v1/stats/basketball/NBA/events/"
    STAT_KEYS = ['scoredPoints'] # enter: 'freeThrowAttempts, fieldGoalAttempts, rebounds, scoredPoints
    THRESHOLD = 10
    GAMES = [2694505]

    logger = ResultLogger(stat_key=",".join(STAT_KEYS), stat_labels=FirstToXboxScorePlayer.STAT_LABELS)

    overall_start = time.time()
    tracker = FirstToXboxScorePlayer(base_url=BASE_URL, logger=logger)
    tracker.process_games_first_to_threshold(GAMES, STAT_KEYS, THRESHOLD)

    elapsed = time.time() - overall_start
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    line = "—" * 100
    centered = f"Total run time: {minutes} min {seconds} sec".center(100)
    print(f"{Fore.CYAN}{line}\n{centered}\n{line}{Style.RESET_ALL}")
