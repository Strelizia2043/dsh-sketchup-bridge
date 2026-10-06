# 补：**房子内部的门**（用户："为什么房间内，这是房子内，你不开门呢"）
#
# 我之前只做了外墙的门窗，内墙全是封死的 —— 人在屋里走不通。
# 内墙的门洞位置用"**墙线断开**"实测（这个方法对**内墙**有效；
# 对外墙无效，因为外墙的玻璃是叠画在完整墙线上的）。
#
# 实测结果（一层内墙）：
#   中庭西壁 x=2250   洞 y 250..2000 (1750)、y 6500..7750 (1250)
#   中庭南壁 y=2250   洞 x 250..1650 (1400)
#   中庭北壁 y=6050   洞 x 700..1700 (1000)
#   中庭东壁 x=6050   洞 x 200..1736 —— 该处与实际相接的墙在 y=1736 处重合，
#                     判为"墙的起端"而非门，**不开**
#
# 门高 2100，上方留门楣。
load 'E:/deepseek工作区/sketchup-bridge/build_from_plan.rb'

S = DshBuild
m = Sketchup.active_model
ents = m.entities
T = 100.0
H1 = 2700.0
DOOR_H = 2100.0

def box(ents, x0, y0, x1, y1, z0, h, name)
  DshBuild.box_on_ground(ents, x0, y0, x1, y1, h, name, z0)
end

# 在**已有内墙组**上开门：把该组删除，按洞口拆成若干段 + 门楣重建
def open_wall(ents, wall_name, axis, at, span, doors)
  # 删掉原组
  old = ents.grep(Sketchup::Group).select { |g| g.name.to_s == wall_name }
  old.each(&:erase!)
  lo, hi = span
  segs, cur, n = [], lo, 0
  doors.sort_by { |d| d[0] }.each do |a, b|
    segs << [cur, a] if a - cur > 1
    cur = b
  end
  segs << [cur, hi] if hi - cur > 1
  segs.each do |a, b|
    n += 1
    if axis == 'h'
      box(ents, a, at - T / 2, b, at + T / 2, 0, H1, "#{wall_name}-#{format('%02d', n)}")
    else
      box(ents, at - T / 2, a, at + T / 2, b, 0, H1, "#{wall_name}-#{format('%02d', n)}")
    end
  end
  # 门楣（洞口上方那段墙）
  doors.each_with_index do |(a, b), i|
    hh = H1 - DOOR_H
    next if hh < 1
    if axis == 'h'
      box(ents, a, at - T / 2, b, at + T / 2, DOOR_H, hh, "#{wall_name}-门楣#{i + 1}")
    else
      box(ents, at - T / 2, a, at + T / 2, b, DOOR_H, hh, "#{wall_name}-门楣#{i + 1}")
    end
  end
  segs.size + doors.size
end

n = 0
n += open_wall(ents, 'W-中庭西壁', 'v', 2250.0, [100.0, 8150.0],
               [[250.0, 2000.0], [6500.0, 7750.0]])
n += open_wall(ents, 'W-中庭南壁', 'h', 2250.0, [100.0, 8150.0],
               [[250.0, 1650.0]])
n += open_wall(ents, 'W-中庭北壁', 'h', 6050.0, [100.0, 8150.0],
               [[700.0, 1700.0]])

puts "  内墙开门：重建 #{n} 段"
puts "  顶层组 #{ents.grep(Sketchup::Group).size} 个"
