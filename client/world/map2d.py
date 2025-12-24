from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
import random

from drone.types import Vec2
from .zones import Zone
from .types import WorldEvent


@dataclass
class Map2D:
    width: float
    height: float
    zones: List[Zone] = field(default_factory=list)

    _drone_in_zones: Dict[str, Set[str]] = field(default_factory=dict, init=False)
    _last_fired: Dict[Tuple[str, str], float] = field(default_factory=dict, init=False)

    _rng: random.Random = field(default_factory=random.Random, init=False)

    def set_seed(self, seed: int) -> None:
        self._rng.seed(seed)

    def bounds(self) -> Tuple[float, float, float, float]:
        return (0.0, self.width, 0.0, self.height)

    def add_zone(self, z: Zone) -> None:
        self.zones.append(z)

    def query_zones(self, pos: Vec2) -> List[Zone]:
        return [z for z in self.zones if z.contains(pos)]

    def update_and_collect_events(self, drone_states: Dict[str, Vec2], ts: float) -> List[WorldEvent]:
 
        events: List[WorldEvent] = []

        for drone_id, pos in drone_states.items():
            inside_now = set()
            for z in self.zones:
                if not z.contains(pos):
                    continue
                inside_now.add(z.id)

                inside_prev = self._drone_in_zones.get(drone_id, set())
                entering = z.id not in inside_prev

                last_fired_ts = self._last_fired.get((drone_id, z.id))
                evs, new_last = z.produce_events(
                    drone_id=drone_id,
                    pos=pos,
                    ts=ts,
                    entering=entering,
                    last_fired_ts=last_fired_ts,
                    rng=self._rng
                )
                events.extend(evs)
                if new_last is not None:
                    self._last_fired[(drone_id, z.id)] = new_last

            self._drone_in_zones[drone_id] = inside_now

        return events
