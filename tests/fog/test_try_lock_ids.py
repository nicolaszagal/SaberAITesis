import numpy as np

from shared.feature_extractor import try_lock_ids


def test_locks_two_largest_boxes_left_to_right():
    boxes = [
        np.array([300, 0, 400, 100], dtype=np.float32),  # pequeño, derecha -> descartado
        np.array([0, 0, 200, 400], dtype=np.float32),     # grande, izquierda -> A
        np.array([250, 0, 450, 400], dtype=np.float32),   # grande, derecha -> B
    ]
    ids = [10, 11, 12]

    id_a, id_b = try_lock_ids(boxes, ids)

    assert (id_a, id_b) == (11, 12)


def test_returns_none_with_fewer_than_two_ids():
    boxes = [np.array([0, 0, 100, 100], dtype=np.float32)]
    assert try_lock_ids(boxes, [5]) == (None, None)


def test_returns_none_when_ids_is_none():
    boxes = [np.array([0, 0, 100, 100], dtype=np.float32)] * 2
    assert try_lock_ids(boxes, None) == (None, None)
