import math

cx = 160   # центр X
cy = 160   # центр Y
r = 100    # радиус

for i in range(360):
    angle = i * math.pi / 180.0
    x = int(cx + r * math.cos(angle))
    y = int(cy + r * math.sin(angle))
    print(f"GoTo({x}, {y});")