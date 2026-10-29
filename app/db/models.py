"""SQLAlchemy ORM models = the schema of data/splatoon.db (ナワバリ first; ranked columns exist but stay NULL).

  Match        one row per match: when, stage/mode/rule, win/lose, paint %, image paths
  MatchPlayer  8 rows per match in HUD slot order (0-3 ally, 4-7 enemy): weapon + result-screen stats
  Event        timeline: t_ms from timer start; death (any slot, HUD), kill (self -> target),
               killed_by (killer -> self), special (own activation), special_ready (own gauge became full)
  Timeline     once per second (own HUD): paint points and special gauge fill; ヤグラ / ホコ track, エリア counts, overtime
  Medal        表彰 screen entries (name = label, or the signature id while unlabelled)
  Weapon       master from the wiki sections (class), used for grouping
Player names are not recorded (random matchmaking): players are identified within a match by HUD slot and weapon.

Schema changes go through Alembic (app/db/migrations): edit the model here, then
`uv run alembic revision --autogenerate -m "..."`, review the generated file, and the app applies it on start-up.
"""
from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, REAL, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

RESULTS = ('win', 'lose', 'draw')
TEAMS = ('ally', 'enemy')
EVENT_TYPES = ('death', 'kill', 'killed_by', 'special', 'special_ready')


def _in(col, values):
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    def to_dict(self, exclude=()):
        """column name -> value, in declaration order (what the REST API returns)"""
        return {c.key: getattr(self, c.key) for c in self.__table__.columns if c.key not in exclude}


class Match(Base):
    __tablename__ = 'matches'
    __table_args__ = (CheckConstraint(_in('result', RESULTS)),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[str] = mapped_column(Text, nullable=False)          # local ISO time of timer start (t=0)
    ended_at: Mapped[str | None] = mapped_column(Text)
    mode: Mapped[str | None] = mapped_column(Text)                          # レギュラーマッチ / バンカラマッチ ...
    rule: Mapped[str | None] = mapped_column(Text)                          # ナワバリバトル / ガチエリア ...
    stage: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(Text)                        # win / lose / draw
    my_pct: Mapped[float | None] = mapped_column(REAL)                      # ナワバリ: 塗りポイント %
    enemy_pct: Mapped[float | None] = mapped_column(REAL)
    my_count: Mapped[int | None] = mapped_column(Integer)                   # ガチ: 'N カウント' (judge / scoreboard); the side that knocked out = 100
    enemy_count: Mapped[int | None] = mapped_column(Integer)
    knockout: Mapped[int | None] = mapped_column(Integer)                   # ガチ: 1 = ノックアウト! (by the winner), 0 = ended on time
    my_team_points: Mapped[int | None] = mapped_column(Integer)             # ガチ: the team's 'Np' under the count (judge) / on the WIN! LOSE... row
    enemy_team_points: Mapped[int | None] = mapped_column(Integer)
    duration_s: Mapped[float | None] = mapped_column(REAL)                  # timer start -> Finish
    source: Mapped[str | None] = mapped_column(Text)                        # 'live' or the video file name
    rule_image: Mapped[str | None] = mapped_column(Text)                    # saved PNG of the rule screen
    result_image: Mapped[str | None] = mapped_column(Text)                  # saved PNG of the result screen
    medal_image: Mapped[str | None] = mapped_column(Text)                   # saved PNG of the 表彰 screen
    raw_json: Mapped[str | None] = mapped_column(Text)                      # full parser output for re-analysis
    notes: Mapped[str | None] = mapped_column(Text)

    players: Mapped[list['MatchPlayer']] = relationship(back_populates='match', order_by='MatchPlayer.slot',
                                                        cascade='all, delete-orphan', passive_deletes=True)
    events: Mapped[list['Event']] = relationship(back_populates='match', order_by='(Event.t_ms, Event.id)',
                                                 cascade='all, delete-orphan', passive_deletes=True)
    medals: Mapped[list['Medal']] = relationship(back_populates='match', order_by='Medal.position',
                                                 cascade='all, delete-orphan', passive_deletes=True)
    timeline: Mapped[list['Timeline']] = relationship(back_populates='match', order_by='Timeline.t_s',
                                                      cascade='all, delete-orphan', passive_deletes=True)


class MatchPlayer(Base):
    __tablename__ = 'match_players'
    __table_args__ = (CheckConstraint(_in('team', TEAMS)),)

    match_id: Mapped[int] = mapped_column(ForeignKey('matches.id', ondelete='CASCADE'), primary_key=True)
    slot: Mapped[int] = mapped_column(Integer, primary_key=True)            # HUD slot 0-7 = rule-screen card order (0-3 ally, 4-7 enemy)
    team: Mapped[str] = mapped_column(Text, nullable=False)                 # ally / enemy
    is_self: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0')
    weapon: Mapped[str | None] = mapped_column(Text)                        # NULL when below the unknown threshold
    weapon_score: Mapped[float | None] = mapped_column(REAL)
    weapon_conf: Mapped[float | None] = mapped_column(REAL)
    points: Mapped[int | None] = mapped_column(Integer)
    kills_assists: Mapped[int | None] = mapped_column(Integer)
    deaths: Mapped[int | None] = mapped_column(Integer)
    specials: Mapped[int | None] = mapped_column(Integer)
    result_row: Mapped[int | None] = mapped_column(Integer)                 # 0-3 position inside the team's result panel (points order)
    link_score: Mapped[float | None] = mapped_column(REAL)                  # HUD slot <-> result row weapon-icon correlation (NULL = slot order arbitrary)

    match: Mapped[Match] = relationship(back_populates='players')


class Event(Base):
    __tablename__ = 'events'
    __table_args__ = (CheckConstraint(_in('type', EVENT_TYPES)), Index('events_match', 'match_id', 't_ms'))

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey('matches.id', ondelete='CASCADE'), nullable=False)
    t_ms: Mapped[int] = mapped_column(Integer, nullable=False)              # since timer start
    clock: Mapped[str | None] = mapped_column(Text)                         # remaining time as shown ('2:38')
    type: Mapped[str] = mapped_column(Text, nullable=False)                 # death / kill / killed_by / special / special_ready
    slot: Mapped[int | None] = mapped_column(Integer)                       # subject: death -> who died, kill/killed_by -> self, special -> who used it
    target_slot: Mapped[int | None] = mapped_column(Integer)                # kill -> victim, killed_by -> killer
    weapon: Mapped[str | None] = mapped_column(Text)                        # killed_by: weapon named in the bubble (when read)
    source: Mapped[str | None] = mapped_column(Text)                        # hud / killfeed / bubble / respawn
    confidence: Mapped[float | None] = mapped_column(REAL)
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    match: Mapped[Match] = relationship(back_populates='events')


class Timeline(Base):
    """own HUD once per second; seconds without a visible HUD have no row"""
    __tablename__ = 'timeline'

    match_id: Mapped[int] = mapped_column(ForeignKey('matches.id', ondelete='CASCADE'), primary_key=True)
    t_s: Mapped[int] = mapped_column(Integer, primary_key=True)             # whole seconds since timer start (0-180; other rules: their length + overtime)
    points: Mapped[int | None] = mapped_column(Integer)                     # 塗りポイント shown top right (first clean read in the second; NULL = unread)
    gauge: Mapped[float | None] = mapped_column(REAL)                       # special gauge fill 0..1 (median over the second)
    ready: Mapped[int | None] = mapped_column(Integer)                      # 1 = gauge full (white ring) in the second
    # ガチヤグラ / ガチホコ: the HUD track, -100 = my goal .. 0 = centre .. +100 = the enemy goal (a position on the line, not a count)
    obj_pos: Mapped[float | None] = mapped_column(REAL)                     # where the ヤグラ / ホコ icon is
    obj_holder: Mapped[str | None] = mapped_column(Text)                    # 'my' / 'enemy' rides / carries it (エリア: holds every zone), NULL = nobody / not read
    my_best: Mapped[float | None] = mapped_column(REAL)                     # how far my team has pushed (0..100, only grows)
    enemy_best: Mapped[float | None] = mapped_column(REAL)                  # how far the enemy has pushed towards my goal (0..100)
    # ガチエリア: both counts as the judge screen gives them (100 - 「のこり」), and obj_holder = the team whose box is lit
    my_count: Mapped[int | None] = mapped_column(Integer)                   # (it holds every zone and is counting down)
    enemy_count: Mapped[int | None] = mapped_column(Integer)
    my_penalty: Mapped[int | None] = mapped_column(Integer)                 # ガチエリア 「+N」 under the box: still to pay before the count moves
    enemy_penalty: Mapped[int | None] = mapped_column(Integer)              # (0 = none; NULL = not read)
    overtime: Mapped[int | None] = mapped_column(Integer)                   # 1 = 「延長中!」 in the second

    match: Mapped[Match] = relationship(back_populates='timeline')


class Medal(Base):
    __tablename__ = 'medals'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey('matches.id', ondelete='CASCADE'), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)                 # label, or the signature id until it is labelled
    rank: Mapped[str | None] = mapped_column(Text)                          # gold / silver
    position: Mapped[int | None] = mapped_column(Integer)                   # order on the 表彰 screen
    sig_id: Mapped[str | None] = mapped_column(Text)                        # signature id in work/signatures.py's library

    match: Mapped[Match] = relationship(back_populates='medals')


class Weapon(Base):
    __tablename__ = 'weapons'

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    class_: Mapped[str | None] = mapped_column('class', Text)               # シューター / ローラー / チャージャー ... (wiki section)
