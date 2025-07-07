from ref_code import add, subtract, simple_calculation

def test():
    assert add(2, 3) == 5
    assert subtract(5, 3) == 2
    assert simple_calculation(2, 3, 4) == 10