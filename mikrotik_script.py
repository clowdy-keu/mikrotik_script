import argparse
import socket
import base64
import re


from paramiko import AutoAddPolicy, SSHClient
from paramiko.ssh_exception import (AuthenticationException, NoValidConnectionsError, SSHException)


class SSHMikrotik(object):

    def __init__(self, address, port, username, password=None, timeout=4):
        self.address = address
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self.connection = self.connect()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.connection:
            self.connection.close()

    def __del__(self):
        self.close()

    def connect(self):
        def pass_generator():
            with open("passwords.csv", "r") as pass_file:
                for line in pass_file:
                    # Если кто-то впишет свои буквы в файл с паролями,
                    # не будем на это смотреть, если не подходит по формату.
                    if len(line.strip()) % 4 == 0:
                        #Пароли храним в зашифрованном виде, нужно еще написать инструмент для удобного
                        #преобразования известного пароля в зашифрованный и его записи в файл.
                        yield base64.b64decode(line.strip().encode("UTF-8")).decode("UTF-8")

        mt_ssh = SSHClient()
        mt_ssh.set_missing_host_key_policy(AutoAddPolicy())

        #Пользуемся генератором, если пользователь сам не ввел пароль.
        if self.password:
            pass_generator = [self.password]
        else:
            with open("passwords.csv", "r") as pass_file:
                pass_generator = pass_generator()
        for next_pass in pass_generator:
            try:
                mt_ssh.connect(self.address, self.port, username=self.username, password=next_pass,
                               timeout=self.timeout, allow_agent=False, look_for_keys=False)
            except (AuthenticationException, NoValidConnectionsError, SSHException) as error:
                print(error)

            except socket.timeout:
                print('Connection timeout')
                if self.timeout < 10:
                    self.timeout += 2

            else:
                return mt_ssh

    def execute(self, command):

        _, stdout, _ = self.connection.exec_command(command)

        stdout = stdout.readlines()
        output = ""

        for line in stdout:
            output = output + line

        if output != "":
            return output.rstrip()
        else:
            return None

    def close(self):
        if self.connection is not None:
            self.connection.close()


def main():
    address_description = """
    Address format <username>@<ip-address>:<port>
    <username>, <port> are optional"""
    command_description = """
    You can use short variants of command:
    uptime->system resource print
    log->log print
    export->export compact"""
    description = """
    This script is for work with Mikrotik.
    It has some nice features, so have fun.
    """
    password_description = """If you don't enter a password, it will be found in the file."""
    parser = argparse.ArgumentParser(prog='Script for Mikrotik control',
                                     formatter_class=argparse.RawTextHelpFormatter,
                                     description=description)
    #Адрес формата <username>@<ip>:<port> и команда обязательные параметры.
    #У адреса обязательный параметр <ip>, остальные опциональны.
    parser.add_argument('address', type=str, help=address_description)
    parser.add_argument('command', type=str, nargs='+', help=command_description)
    parser.add_argument('-p', '--password', type=str, required=False, default=None, help=password_description)
    parser.add_argument('-t', '--timeout', type=int, required=False, default=4)

    args = parser.parse_args()

    short_commands = {
        "uptime": "system resource print",
        "log": "log print",
        "export": "export compact"
    }

    command = " ".join(args.command)
    if command in short_commands:
        command = short_commands[command]

    port = 22
    username = 'Admin'

    #Распарсить можно регуляркой, но как отличить ситуацию в которой будет случайно формат <username>@:<port>, например
    #непонятно с ходу, так что пока так, наглядно.
    if '@' in args.address:
        username, args.address = [item for item in args.address.split('@')]

    if ':' in args.address:
        args.address, port = [item for item in args.address.split(':')]

    #Модификация вывода команды system resource print
    def mod_sys_res_print(output):
        parameters_from_mikrotik = list(map(list, zip([item.split(":", 1)[0].replace(" ", "") for item in output.split("\n")],
                                         [item.split(":", 1)[1].strip() for item in output.split("\n")])))

        with open("params_for_sys_res.csv", "r") as params_file:
            parameters_for_output = [item.split(',') for item in params_file.read().splitlines()][1::]
        #Если в файле оказалось некорректное число параметров, приводим к 3 необходимым.
        for i in range(len(parameters_for_output)):
            while len(parameters_for_output[i]) < 3:
                parameters_for_output[i].append('')
            while len(parameters_for_output[i]) > 3:
                parameters_for_output[i] = parameters_for_output[i][:3:]

        #Проверка, не превышены ли какие-то значения
        def checking_params(parameters_from_mikrotik, parameters_for_output):

            def uptime_conversion(*args):

                def dict_wdhms_in_sec(time_dict):
                    seconds = 0
                    for item in time_dict:
                        if item == "s":
                            seconds += int(time_dict[item])
                        if item == "m":
                            seconds += int(time_dict[item]) * 60
                        elif item == "h":
                            seconds += int(time_dict[item]) * 60 * 60
                        elif item == "d":
                            seconds += int(time_dict[item]) * 60 * 60 * 24
                        elif item == "w":
                            seconds += int(time_dict[item]) * 60 * 60 * 24 * 7
                    return seconds

                result = [''] * len(args)
                for i, parameter in enumerate(args):
                    if parameter != '':
                        if re.match(r"(\d+[wdhms])+", parameter).group() == parameter:
                            time_dict = {}.fromkeys("wdhms", 0)
                            for sym in "wdhms":
                                if re.search(sym, parameter) is not None:
                                    next_value = re.split(sym, parameter)
                                    time_dict[str(sym)] += int(next_value[0])
                                    parameter = next_value[1]
                            time_sec = dict_wdhms_in_sec(time_dict)
                            result[i] = int(time_sec)
                        else:
                            print("Something wrong with uptime parameter, please check it")
                            result[i] = -1
                return result
            #Версии дело тонкое, если там будут условные beta alpha - это нужно будет договариваться
            #какая версия больше/меньше и допиливать.
            #Так как сравнение идет в универсальной функции - нам нужны численно сравнимые значения
            #Придумал так: добиваем номер версии нулями до формата #.#.#.#.#.#, так чтобы с запасом
            #Формируем большое число(например 600450008000000000000), которое на самом деле
            #имеет формат 6.0045.0008.0000.0000.0000, то есть в каждом разряде есть запас под
            #9999 подверсий (в первом нули отбрасываются). Их сравниваем.
            def version_conversion(*args):
                result = [''] * len(args)
                for i, parameter in enumerate(args):
                    if parameter != '':
                        version = re.search(r"[0-9.]*", parameter).group().split('.')
                        while len(version) < 6:
                            version.append('0')
                        version = int(''.join([item.zfill(4) for item in version]))
                        result[i] = int(version)
                return result
            #Учитываем единицы измерения, переводим все в KiB
            def memory_and_hdd_coversion(*args):
                result = [''] * len(args)
                for i, parameter in enumerate(args):
                    if parameter != '':
                        unit_dict = {'KiB': 0, 'MiB': 1, 'GiB': 2, 'TiB': 3, 'PiB': 4, 'EiB': 5}
                        unit = re.search(r"[A-Za-z]+", parameter)
                        if unit is not None:
                            unit = unit.group()
                        else:
                            unit = ''
                        memory = float(re.search(r"[^A-Za-z]*", parameter).group())
                        if unit in unit_dict:
                            memory *= 2 ** (10 * unit_dict[unit])
                            result[i] = int(memory)
                        else:
                            print("Please check out memory's unit of measurement")
                            result[i] = -1
                return result

            def cpu_conversion(*args):
                result = [''] * len(args)
                for i, parameter in enumerate(args):
                    if parameter != '':
                        cpu = int(re.search(r"\d+", parameter).group())
                        result[i] = int(cpu)
                return result
            #Совсем без деревьев не обошлось, если в min/max value приходят пустые значения
            #нужно как-то с ними поступать, двойное сравнение не сработает.
            def is_value_in_range(*args):
                check_value, min_value, max_value = args
                if min_value == '' and max_value == '':
                    return True
                if min_value == '':
                    return check_value <= max_value
                if max_value == '':
                    return check_value >= min_value
                if min_value > max_value:
                    print("Minimum value is bigger than maximum, check it")
                    return False
                else:
                    return min_value <= check_value <= max_value
            #Функции исключительно конвертируют, ничего не знаю о том, что именно им приходит
            parameters_for_control = {
                "uptime": uptime_conversion,
                "version": version_conversion,
                "free-memory": memory_and_hdd_coversion,
                "cpu-load": cpu_conversion,
                "free-hdd-space": memory_and_hdd_coversion
            }

            for parameter, min_value, max_value in parameters_for_output:
                try:
                    value_for_check = \
                    parameters_from_mikrotik[[item[0] for item in parameters_from_mikrotik].index(parameter)][1]
                    if parameter in parameters_for_control:
                        pack_for_coversion = parameters_for_control.get(parameter)\
                            (value_for_check, min_value, max_value)
                        if not is_value_in_range(*pack_for_coversion):
                            print("Controlled parameter {} = {} is out of range min({}) - max({})"
                                  .format(parameter, value_for_check, min_value, max_value))
                    else:
                        continue
                except ValueError:
                    print("Controlled parameter '{}' is absent in the output ".format(parameter))

        dict_need_params = [item for item in parameters_from_mikrotik if
                            item[0] in [item[0] for item in parameters_for_output]]
        #Выводим интересное
        for key, value in dict_need_params:
            print("%-15s: %25s" % (key, value))

        #Проверяем соответствие границам и показываем warning_message
        checking_params(parameters_from_mikrotik, parameters_for_output)
    #Задаем соответствие между командами, которым нужен оригинальный вывод и функциями-обработчиками.
    modified_commands = {
        "system resource print": mod_sys_res_print
    }

    with SSHMikrotik(args.address, port, username, args.password, args.timeout) as mt_ssh:
        try:
            #Если нужен оригинальный вывод, используем функцию-обработчик.
            if command in modified_commands:
                modified_commands.get(command)(mt_ssh.execute(command))
            else:
                print(mt_ssh.execute(command))
        except Exception:
            print("Something terrible happened")

if __name__ == '__main__':
    main()
