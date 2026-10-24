"""Reusable SELECTs built on the models: the stat tables the web shows (formerly SQLite views), and the
per-match row with the player's own line. Everything returns dicts (column order = table column order)."""
from sqlalchemy import case, func, select
from sqlalchemy.orm import aliased
from .models import Event, Match, MatchPlayer, Medal

# my own row of a match (is_self = 1); LEFT JOIN so matches whose result screen was not read still list
MY = aliased(MatchPlayer, name='p')
MY_JOIN = (MY.match_id == Match.id) & (MY.is_self == 1)

def wins(result_col=Match.result):
    return func.sum(case((result_col == 'win', 1), else_=0))


def win_pct(result_col=Match.result):
    return func.round(100.0 * wins(result_col) / func.count(), 1)


def rows(session, stmt):
    return [dict(r._mapping) for r in session.execute(stmt)]


def match_row(*extra):
    """the list / overlay columns of a match + my row"""
    return (select(Match.id, Match.started_at, Match.mode, Match.rule, Match.stage, Match.result, Match.my_pct, Match.enemy_pct,
                   Match.duration_s, Match.source, Match.notes,
                   MY.weapon, MY.points, MY.kills_assists, MY.deaths, MY.specials, *extra)
            .select_from(Match).outerjoin(MY, MY_JOIN))


def match_filter(M=Match, since=None, mode=None):
    """WHERE conditions narrowing the stats to some matches: started at/after `since` (ISO local time), of one `mode`"""
    conds = []
    if since: conds.append(M.started_at >= since)
    if mode: conds.append(M.mode == mode)
    return conds


def my_matches(since=None, mode=None):
    """what the stat tables aggregate over: one row per match with my weapon / stats (matches without my row are skipped)"""
    return (select(Match.id, Match.started_at, Match.stage, Match.mode, Match.rule, Match.result, Match.my_pct, Match.enemy_pct,
                   MY.weapon, MY.points, MY.kills_assists, MY.deaths, MY.specials)
            .select_from(Match).join(MY, MY_JOIN).where(*match_filter(Match, since, mode))).subquery('my_matches')


def overview(**f):
    """one row: totals / averages over my matches (the dashboard's headline numbers)"""
    m = my_matches(**f)
    return select(func.count().label('games'), func.coalesce(wins(m.c.result), 0).label('wins'),
                  func.coalesce(func.sum(case((m.c.result == 'lose', 1), else_=0)), 0).label('losses'),
                  func.round(func.avg(m.c.kills_assists), 2).label('avg_ka'), func.round(func.avg(m.c.deaths), 2).label('avg_d'),
                  func.round(func.avg(m.c.specials), 2).label('avg_sp'), func.round(func.avg(m.c.points)).label('avg_points'),
                  func.round(func.avg(m.c.my_pct), 1).label('avg_pct'),
                  func.sum(m.c.kills_assists).label('sum_ka'), func.sum(m.c.deaths).label('sum_d'))


def recent_results(limit=20, **f):
    """my newest matches' results, newest first (the form strip / current streak)"""
    m = my_matches(**f)
    return select(m.c.id, m.c.started_at, m.c.result, m.c.weapon, m.c.stage).order_by(m.c.started_at.desc(), m.c.id.desc()).limit(limit)


def daily_stats(**f):
    """日別 (新しい日から)"""
    m = my_matches(**f)
    day = func.substr(m.c.started_at, 1, 10).label('day')
    return (select(day, func.count().label('games'), wins(m.c.result).label('wins'), win_pct(m.c.result).label('win_pct'),
                   func.round(func.avg(m.c.kills_assists), 2).label('avg_ka'), func.round(func.avg(m.c.deaths), 2).label('avg_d'),
                   func.round(func.avg(m.c.specials), 2).label('avg_sp'), func.round(func.avg(m.c.points)).label('avg_points'))
            .group_by(day).order_by(day.desc()))


def weapon_stats(**f):
    """自分の武器別"""
    m = my_matches(**f)
    return (select(m.c.weapon, func.count().label('games'), wins(m.c.result).label('wins'), win_pct(m.c.result).label('win_pct'),
                   func.round(func.avg(m.c.kills_assists), 2).label('avg_ka'), func.round(func.avg(m.c.deaths), 2).label('avg_d'),
                   func.round(func.avg(m.c.specials), 2).label('avg_sp'), func.round(func.avg(m.c.points)).label('avg_points'))
            .group_by(m.c.weapon).order_by(func.count().desc()))


def stage_stats(**f):
    """ステージ別"""
    m = my_matches(**f)
    return (select(m.c.stage, func.count().label('games'), wins(m.c.result).label('wins'), win_pct(m.c.result).label('win_pct'),
                   func.round(func.avg(m.c.kills_assists), 2).label('avg_ka'), func.round(func.avg(m.c.deaths), 2).label('avg_d'),
                   func.round(func.avg(m.c.points)).label('avg_points'))
            .group_by(m.c.stage).order_by(func.count().desc()))


def enemy_weapon_stats(**f):
    """相手の武器別: 遭遇数、遭遇時の勝率、やられた/たおした回数"""
    k = aliased(MatchPlayer, name='k'); v = aliased(MatchPlayer, name='v'); e = aliased(Event, name='e'); em = aliased(Match, name='em')
    killed_me = (select(func.count()).select_from(e).join(k, (k.match_id == e.match_id) & (k.slot == e.target_slot))
                 .join(em, em.id == e.match_id).where(e.type == 'killed_by', k.weapon == MatchPlayer.weapon, *match_filter(em, **f))
                 .scalar_subquery())
    i_killed = (select(func.count()).select_from(e).join(v, (v.match_id == e.match_id) & (v.slot == e.target_slot))
                .join(em, em.id == e.match_id).where(e.type == 'kill', v.weapon == MatchPlayer.weapon, *match_filter(em, **f))
                .scalar_subquery())
    return (select(MatchPlayer.weapon, func.count().label('seen'), wins().label('wins'), win_pct().label('win_pct'),
                   killed_me.label('killed_me'), i_killed.label('i_killed'))
            .select_from(MatchPlayer).join(Match, Match.id == MatchPlayer.match_id)
            .where(MatchPlayer.team == 'enemy', MatchPlayer.weapon.is_not(None), *match_filter(Match, **f))
            .group_by(MatchPlayer.weapon).order_by(func.count().desc()))


def medal_stats(**f):
    """表彰の種類別"""
    return (select(Medal.name, Medal.rank, func.count().label('n')).join(Match, Match.id == Medal.match_id)
            .where(*match_filter(Match, **f)).group_by(Medal.name, Medal.rank).order_by(func.count().desc()))


def my_timeline(**f):
    """自分のキル/デスを 30 秒刻みで"""
    from_s = ((Event.t_ms // 30000) * 30).label('from_s')
    return (select(from_s, Event.type, func.count().label('n'))
            .select_from(Event).join(MY, (MY.match_id == Event.match_id) & (MY.slot == Event.slot) & (MY.is_self == 1))
            .join(Match, Match.id == Event.match_id)
            .where(Event.type.in_(('kill', 'killed_by', 'death')), *match_filter(Match, **f))
            .group_by(from_s, Event.type).order_by(from_s, Event.type))


STATS = {'overview': overview, 'weapon_stats': weapon_stats, 'stage_stats': stage_stats, 'enemy_weapon_stats': enemy_weapon_stats,
         'medal_stats': medal_stats, 'my_timeline': my_timeline, 'daily_stats': daily_stats}


def stats(session, since=None, mode=None):
    """every stat table, optionally only over matches started at/after `since` (ISO local time) / of one `mode`"""
    return {name: rows(session, build(since=since, mode=mode)) for name, build in STATS.items()}


def killed_by_weapons(since=None, limit=3):
    """weapons that killed me most (killed_by events -> the killer slot's weapon), optionally for matches started at/after `since`"""
    k = aliased(MatchPlayer, name='k')
    q = (select(k.weapon, func.count().label('n')).select_from(Event).join(Match, Match.id == Event.match_id)
         .join(k, (k.match_id == Event.match_id) & (k.slot == Event.target_slot))
         .where(Event.type == 'killed_by', k.weapon.is_not(None)))
    if since: q = q.where(Match.started_at >= since)
    return q.group_by(k.weapon).order_by(func.count().desc(), k.weapon).limit(limit)


def match_counts():
    """(matches, wins) over everything"""
    return select(func.count(), func.coalesce(wins(), 0)).select_from(Match)
