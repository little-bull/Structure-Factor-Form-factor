import os
import math
import time
import numpy as np
from functools import cache
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import ProcessPoolExecutor, as_completed

def log_error(*args):
    print("error : ", *args)

def log_info(*args):
    print("log : ", *args)

def file_line_generator(file_path):
    if not os.path.exists(file_path):
        log_error("{} 不存在！".format(file_path))
        return 
    with open(file_path,"r") as f:
        for line in f:
            yield line.strip()

def Q_generator(q0, qmax, M):
    step = (qmax - q0) / M
    cur = q0
    while cur < qmax:
        yield cur
        cur += step

class Pos():
    def __init__(self,x = 0, y = 0, z = 0):
        self.x = x
        self.y = y
        self.z = z

    def dis(self,other):
        dis_x = other.x - self.x
        dis_y = other.y - self.y
        dis_z = other.z - self.z
        dis_list = [dis_x, dis_y, dis_z]

        return math.sqrt(sum(d * d for d in dis_list))

class Box():
    def __init__(self, **config):
        self.x_min = config["x_min"]
        self.x_max = config["x_max"]

        self.y_min = config["y_min"]
        self.y_max = config["y_max"]

        self.z_min = config["z_min"]
        self.z_max = config["z_max"]

    def mod_in_box(self, pos):
        len_x = self.x_max - self.x_min
        len_y = self.y_max - self.y_min
        len_z = self.z_max - self.z_min

        x = (pos.x - self.x_min) % len_x + self.x_min
        y = (pos.y - self.y_min) % len_y + self.y_min
        z = (pos.z - self.z_min) % len_z + self.z_min

        new_pos = Pos(x, y, z)

        return new_pos

class Atom():
    def __init__(self,atom_id, atom_type, x, y, z):
        self.atom_id = atom_id
        self.atom_type = atom_type
        self.pos = Pos(x, y, z)
        self.cache_dis_dict = {}

    def dis(self, other):
        # cache一下加快避免重复计算
        if self.atom_id in other.cache_dis_dict:
            return other.cache_dis_dict[self.atom_id]
        if other.atom_id in self.cache_dis_dict:
            return self.cache_dis_dict[other.atom_id]

        dis = self.pos.dis(other.pos)
        self.cache_dis_dict[other.atom_id] = dis
        other.cache_dis_dict[self.atom_id] = dis

        return dis

    def set_pos(self, pos):
        self.pos = pos

    def get_pos(self):
        return self.pos

    def get_atom_id():
        return self.atom_id

    def __eq__(self, other):
        return self.atom_id == other.atom_id

    def __hash__(self):
        return hash(self.atom_id)

class Frame():
    def __init__(self):
        self.atom_list = []
        self.atom_count = 0
        self.box = None
        self.total_dis = 0
        self.frame_id = -1

    def set_frame_id(self, frame_id):
        self.frame_id = frame_id

    def set_atom_count(self, atom_count):
        self.atom_count = atom_count

    def get_atom_count(self):
        return self.atom_count
    
    def add_atom(self, atom):
        # 重定位
        old_pos = atom.get_pos()
        new_pos = self.box.mod_in_box(old_pos)
        atom.set_pos(new_pos)
        self.atom_list.append([new_pos.x, new_pos.y, new_pos.z])

    def set_box(self, box):
        self.box = box

    def cal_old(self,Q):
        pass

    def cal_total_dis(self, Q):
        Q = Q / (self.box.x_max - self.box.x_min)
        # 确保输入是 numpy 数组
        positions = np.array(self.atom_list)

        # 使用广播机制计算两两点之间的向量差
        diff = positions[:, np.newaxis, :] - positions[np.newaxis, :, :]  # (N, N, 3)

        # 计算欧几里得距离矩阵
        distance_matrix = np.linalg.norm(diff, axis=-1)  # (N, N)
        distance_matrix = distance_matrix * Q
        # 排除自身距离（对角线元素为 0）
        np.fill_diagonal(distance_matrix, 0)

        # 计算距离的总和
        total_distance = np.sum(distance_matrix)

        # 计算 sin 值矩阵
        sin_matrix = np.sin(distance_matrix)

        # 计算 sin 值的总和
        total_sin = np.sum(sin_matrix)


        N = len(self.atom_list)
        K = 1 / ((N + 1) * (N + 1)) 
        # log_info(N,K,total_dis)
        # print(Q,total_sin,total_distance)
        self.total_dis = K * (total_sin / total_distance)


    def get_total_dis(self):
        return self.total_dis


class AverageCalculator():
    def __init__(self, file_path, atom_chain_count = 100):
        self.file_lines = file_line_generator(file_path)
        self.atom_chain_count = atom_chain_count
        self.frames = []
        self.parse_frames()

    def parse_box_pos(self, line):
        offsets = line.split(" ")
        offset_1,offset_2 = float(offsets[0]), float(offsets[1])
        return offset_1,offset_2

    def parse_atom_pos(self, line):
        info = line.split(" ")
        atom_id     = int(info[0])
        atom_type   = int(info[1])
        x           = float(info[2])
        y           = float(info[3])
        z           = float(info[4])
        return atom_id, atom_type, x, y, z

    def parse_frames(self):
        line_index = 0
        box_config = {}
        sklp_line = set((2, 4, 8))
        for line in self.file_lines:
            # 新建一个frame
            if line_index == 0:
                self.frames.append(Frame())
            elif line_index == 1:
                frame_id = int(line)
                self.frames[-1].set_frame_id(frame_id)
            #跳过无用行
            elif line_index in sklp_line:
                line_index += 1
                continue
            #解析原子数
            elif line_index == 3:
                total_atom = int(line)
                self.frames[-1].set_atom_count(total_atom)
            #解析box边界
            elif line_index == 5:
                box_config['x_min'], box_config['x_max'] = self.parse_box_pos(line)
            elif line_index == 6:
                box_config['y_min'], box_config['y_max'] = self.parse_box_pos(line)
            elif line_index == 7:
                box_config['z_min'], box_config['z_max'] = self.parse_box_pos(line)  
                box = Box(**box_config)
                self.frames[-1].set_box(box)
            # 解析原子数据
            else:
                total_atom = self.frames[-1].get_atom_count()
                # print(line_index,total_atom == line_index, total_atom, type(total_atom), line)
                atom_id, atom_type, x, y, z = self.parse_atom_pos(line)
                atom = Atom(atom_id, atom_type, x, y, z)
                self.frames[-1].add_atom(atom)
                # print(atom.atom_id,"add__________")

            #下一行
            line_index += 1

            #重新添加下一个frame
            if line_index == self.frames[-1].get_atom_count() + 9:
                line_index = 0

    # 单线程
    def cal_arvage(self, Q):
        frame_total = 0
        for frame in self.frames:
            frame.cal_total_dis(Q)
            frame_total += frame.get_total_dis()
        return frame_total / len(self.frames)

    # 多线程的方式计算，max_workers = 你电脑的线程数
    def cal_arvage_multithread(self, Q):
        frame_total = 0
        with ProcessPoolExecutor(max_workers=3) as executor:  # 创建线程池
            future_to_frame = {executor.submit(frame.cal_total_dis, Q): frame for frame in self.frames}
            for future in as_completed(future_to_frame):
                frame = future_to_frame[future]
                frame_total += frame.get_total_dis()
        return frame_total / len(self.frames)

    def format_print_cal_result(self, Q , multithread):
        # P = self.cal_arvage(Q)
        P = 0
        if multithread:
            P = self.cal_arvage_multithread(Q)
        else:
            P = self.cal_arvage(Q) 
        return format(P, ".15e"),format(Q, ".15e")


# 获取当前文件所在的目录
CUR_DIR = os.path.abspath(os.path.dirname(__file__))
# 获取当前文件的绝对路径
current_file_path = os.path.abspath(__file__)

DATA_DIR = os.path.join(CUR_DIR, "data")
RESULT_DIR = os.path.join(CUR_DIR, "result")

def save_result(file_name, result):
    file_path = os.path.join(RESULT_DIR, file_name.replace("atom","dat"))
    with open(file_path,"w") as f:
        f.write("# Total structure factor for atom types: \n")
        f.write("# { 1(5) }in system. \n")
        f.write("# Q-values       P(Q)  \n")
        f.write("\n".join(result))



def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(RESULT_DIR, exist_ok=True)


    file_names = []
    file_names.append("test.atom")
    # file_names.append("md100.atom")
    # file_names.append("md125.atom")
    # file_names.append("md150.atom")
    # file_names.append("md175.atom")


    for file_name in file_names:
        file_path = os.path.join(DATA_DIR,file_name)
        q0, qmax, M = 1 * 2 * math.pi,200 * 2 * math.pi, 200
        result = []
        for Q in Q_generator(q0, qmax, M):
            log_info("cal_begin", int(time.time()))
            P,Q = ac.format_print_cal_result(Q,True)
            result_line = "{}      {}".format(Q,P)
            result.append(result_line)
            log_info("cal_end", int(time.time()))

        save_result(file_name, result)

def spilit2test():
    contentList = []
    with open("data/md100.atom","r") as f:
        for i in range(5009 * 20 - 1):
            contentList.append(f.readline())
    with open("data/test.atom","w") as f:
        f.write("".join(contentList))

def print_help():
    print("1.文件放入data目录")
    print("2.结果产出在result目录")

# def test():
    # Q = 1
    # # 确保输入是 numpy 数组
    # positions = np.array([[1,1,1],[0,0,0]])

    # # 使用广播机制计算两两点之间的向量差
    # diff = positions[:, np.newaxis, :] - positions[np.newaxis, :, :]  # (N, N, 3)
    # print(diff)
    # # 计算欧几里得距离矩阵
    # distance_matrix = np.linalg.norm(diff, axis=-1)  # (N, N)
    # print(distance_matrix)
    # distance_matrix = distance_matrix * Q
    # # 排除自身距离（对角线元素为 0）
    # np.fill_diagonal(distance_matrix, 0)

    # # 计算距离的总和
    # total_distance = np.sum(distance_matrix)

    # # 计算 sin 值矩阵
    # sin_matrix = np.sin(distance_matrix)

    # # 计算 sin 值的总和
    # total_sin = np.sum(sin_matrix)

    # print(total_sin,total_distance)

    # N = len(self.atom_list)
    # K = 1 / ((N + 1) * (N + 1)) 
    # log_info(N,K,total_dis)
    # print(Q,total_sin,total_distance)
    # self.total_dis = K * (total_sin / total_distance)

if __name__ == '__main__':
    print_help()
    main()
    # test()
    # spilit2test()













