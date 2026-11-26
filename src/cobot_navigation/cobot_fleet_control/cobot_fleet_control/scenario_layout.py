"""선반 열·고객 자리 설정으로 운송 경로 표를 만들고 검사한다."""

from .scenario_contracts import identifier, ROUTE_ARMS

ROUTE_KEYS = {'pickup', 'dropoff', 'pickup_arm', 'dropoff_arm', 'lane'}
# 지점 자리(고객 자리) 경로: 고객 지점과 회수 반환 구역·팔이 더 있다.
CUSTOMER_ROUTE_KEYS = ROUTE_KEYS | {'customer', 'restock', 'restock_arm'}
# 고객 자리는 구역 밖 매장 바닥이다. 구역 진입은 zone_manager 가 한 대씩 막으므로 통로(lane)는 생략할 수 있다.
ROUTE_KEY_SETS = (ROUTE_KEYS, CUSTOMER_ROUTE_KEYS, CUSTOMER_ROUTE_KEYS - {'lane'})


def check_routes(routes):
    """경로 칸이 빠짐없고, 한 경로 안의 작업장과 팔이 서로 다른지 본다."""
    for route in routes.values():
        if set(route) not in ROUTE_KEY_SETS:
            raise ValueError('route: pickup, dropoff, pickup_arm, dropoff_arm, lane 필요')
        for name, value in route.items():
            identifier(value, name)
        spots = [route[k] for k in ('pickup', 'dropoff', 'restock') if k in route]
        if len(set(spots)) != len(spots):
            raise ValueError('상차·하차(정리)·반환 지점은 서로 달라야 합니다')
        arms = [route[k] for k in ROUTE_ARMS if k in route]
        if len(set(arms)) != len(arms):
            raise ValueError('이 경로의 팔은 서로 다른 작업 구역을 사용해야 합니다')


def build_layout(routes, shelf, destinations, customer_return=None):
    """
    선반 열과 고객 자리 설정을 검증하고 (열, 자리) 조합마다 운송 경로를 만든다.

    자리는 두 가지다.
    - 하차 구역 자리 {dropoff, dropoff_arm, lane}: 하차 팔이 내려놓고 고객이 받는다 (기존).
    - 지점 자리 {point[, lane]}: 로봇이 그 지점(고객 자리, 구역이 아닌 일반 지점)으로 가서 고객이
      핑키에서 직접 꺼낸다. 회수하면 customer_return 의 정리 구역(arrange)·반환 구역(restock)을 거친다.
      경로 칸: customer=지점, dropoff/dropoff_arm=정리 구역·팔, restock/restock_arm=반환 구역·팔.
      lane 을 생략하면 통로 예약 없이 주행한다.
    """
    routes = dict(routes)
    shelf = dict(shelf or {})
    destinations = {key: dict(value) for key, value in (destinations or {}).items()}
    if not shelf and not destinations:
        return {}, {}, routes
    back = dict(customer_return or {})
    if back and set(back) != {'arrange', 'arrange_arm', 'restock', 'restock_arm'}:
        raise ValueError('customer_return: arrange, arrange_arm, restock, restock_arm 필요')
    rows = shelf.get('rows')
    columns = shelf.get('columns') or {}
    if (set(shelf) - {'rows', 'columns'} or isinstance(rows, bool)
            or not isinstance(rows, int) or not 1 <= rows <= 100):
        raise ValueError('shelf: rows(1~100 정수)와 columns 필요')
    for column, pickup in columns.items():
        if (isinstance(column, bool) or not isinstance(column, int)
                or not 1 <= column <= 100):
            raise ValueError('shelf.columns: 열 번호는 1~100 정수')
        if not isinstance(pickup, dict) or set(pickup) != {'pickup', 'pickup_arm'}:
            raise ValueError('shelf.columns: 열마다 pickup, pickup_arm 필요')
    for name, target in destinations.items():
        identifier(name, 'destination')
        keys = set(target) - {'name'} if isinstance(target, dict) else None
        if (keys not in ({'dropoff', 'dropoff_arm', 'lane'}, {'point', 'lane'}, {'point'})
                or not isinstance(target.get('name', name), str)):
            raise ValueError(
                'destinations: 자리마다 dropoff, dropoff_arm, lane 또는 point[, lane] 필요')
        if 'point' in target and not back:
            raise ValueError('지점 자리(point)는 customer_return(회수 정리·반환 구역) 설정 필요')
        for column, pickup in columns.items():
            route = f'col{column}__{name}'
            if route in routes:
                raise ValueError('선반·자리 경로 이름이 routes와 겹칩니다: ' + route)
            if 'point' in target:
                routes[route] = dict(pickup, customer=target['point'],
                                     dropoff=back['arrange'], dropoff_arm=back['arrange_arm'],
                                     restock=back['restock'], restock_arm=back['restock_arm'],
                                     **({'lane': target['lane']} if 'lane' in target else {}))
            else:
                routes[route] = dict(pickup, dropoff=target['dropoff'],
                                     dropoff_arm=target['dropoff_arm'], lane=target['lane'])
    return dict(rows=rows, columns=columns), destinations, routes
