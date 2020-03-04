import argparse
import socket
import base64
import re
from distutils.version import LooseVersion


from paramiko import AutoAddPolicy, SSHClient
from paramiko.ssh_exception import (AuthenticationException, NoValidConnectionsError, SSHException)


class SSHMikrotik(object):

    def __init__(self, address, port, username, password=None):
        self.address = address
        self.port = port
        self.username = username
        self.password = password
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
        #Нужно разобраться со структурой, как будто ее можно улучшить здесь.
        if self.password is None:
            for next_pass in pass_generator():
                try:
                    mt_ssh.connect(self.address, self.port, username=self.username, password=next_pass,
                                    timeout=1, allow_agent=False, look_for_keys=False)

                except (AuthenticationException, NoValidConnectionsError, SSHException) as error:
                    print(error)

                except socket.timeout:
                    print('Connection timeout')
                    break

                else:
                    return mt_ssh
        else:
            try:
                mt_ssh.connect(self.address, self.port, username=self.username, password=self.password,
                            timeout=1, allow_agent=False, look_for_keys=False)
            except (AuthenticationException, NoValidConnectionsError, SSHException) as error:
                print(error)

            except socket.timeout:
                print('Connection timeout')

            else:
                return mt_ssh

    def execute(self, command):
        try:
            if isinstance(command, list):
                command = " ".join(command) 
        except TypeError:
            print('Something wrong with your command!')

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
    parser = argparse.ArgumentParser()
    #Адрес формата <username>@<ip>:<port> и команда обязательные параметры.
    #У адреса обязательный параметр <ip>, остальные опциональны.
    parser.add_argument('address', type=str)
    parser.add_argument('command', type=str, nargs='+')
    parser.add_argument('-p', '--password', type=str, required=False, default=None)

    args = parser.parse_args()

    #Хочется от этого избавиться, нужно погрузиться в argparse.
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
        list_params = list(map(list, zip([item.split(":", 1)[0].replace(" ", "") for item in output.split("\n")],
                                         [item.split(":", 1)[1].strip() for item in output.split("\n")])))

        with open("params_for_sys_res.csv", "r") as params_file:
            list_need_params = [item.split(',') for item in params_file.read().splitlines()]

        #Проверка, не превышены ли какие-то значения
        def checking_params(list_params, list_need_params):

            #Функции отдельно под каждый параметр со своей логикой парсинга.
            def uptime_check(checked_param, param):

                sign_compr = re.search(r'\W*', param).group()
                param = re.sub(sign_compr, '', param)

                time_dict_need = {}.fromkeys("wdhms", 0)
                time_dict_check = {}.fromkeys("wdhms", 0)

                for sym in "wdhms":
                    next_time_value_need = re.split(sym, param)
                    next_time_value_check = re.split(sym, checked_param)

                    if len(next_time_value_need) > 1:
                        time_dict_need[str(sym)] += int(next_time_value_need[0])
                        param = next_time_value_need[1]

                    if len(next_time_value_check) > 1:
                        time_dict_check[str(sym)] += int(next_time_value_check[0])
                        checked_param = next_time_value_check[1]
                #Переводим в секунды для сравнения значений
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

                time_sec_check = dict_wdhms_in_sec(time_dict_check)
                time_sec_need = dict_wdhms_in_sec(time_dict_need)

                #Этот блок хочется сделать элегантнее, напрямую используя sign_compr в котором храним знак сравнения
                #чтобы не городить иерархию
                result = True
                if sign_compr == '<':
                    result = time_sec_check < time_sec_need
                elif sign_compr == '<=':
                    result = time_sec_check <= time_sec_need
                elif sign_compr == '>':
                    result = time_sec_check > time_sec_need
                elif sign_compr == '>=':
                    result = time_sec_check >= time_sec_need
                elif sign_compr == '=':
                    result = time_sec_check == time_sec_need
                else:
                    print("Wrond comparison sign format")

                return result

            def version_check(checked_param, param):

                sign_compr = re.search(r'[<>=]*', param).group()
                param = re.sub(sign_compr, '', param)

                need_version = re.search(r"[0-9.]*", param).group()
                check_version = re.search(r"[0-9.]*", checked_param).group()

                result = True
                if sign_compr == '<':
                    result = LooseVersion(check_version) < LooseVersion(need_version)
                elif sign_compr == '<=':
                    result = LooseVersion(check_version) <= LooseVersion(need_version)
                elif sign_compr == '>':
                    result = LooseVersion(check_version) > LooseVersion(need_version)
                elif sign_compr == '>=':
                    result = LooseVersion(check_version) >= LooseVersion(need_version)
                elif sign_compr == '=':
                    result = LooseVersion(check_version) == LooseVersion(need_version)
                else:
                    print("Wrond comparison sign format")

                return result
            #пустышки
            def memory_check(checked_param, param):
                return False

            def cpu_check(checked_param, param):
                return False

            def hdd_check(checked_param, param):
                return False

            #Задаем соответствие между интересными параметрами и функциями-обработчиками
            controlled_params = {
                "uptime": uptime_check,
                "version": version_check,
                "free-memory": memory_check,
                "cpu-load": cpu_check,
                "free-hdd-space": hdd_check
            }

            warning_params = []
            for param in list_need_params:
                if param[0] in controlled_params:
                    for item in list_params:
                        if item[0] == param[0]:
                            checked_param = item
                            break
                    else:
                        print("Controlled parameter '{}' is absent in the output".format(param[0]))
                        continue
                    if controlled_params.get(param[0])(checked_param[1], param[1]):
                        warning_params.append(checked_param[0])

            return (warning_params)

        dict_need_params = {item[0]: item[1] for item in list_params if
                            item[0] if item[0] in [item[0] for item in list_need_params]}

        for key, value in dict_need_params.items():
            print("%-15s: %25s" % (key, value))

        for warning in checking_params(list_params, list_need_params):
            print("{} is out of range".format(warning))

    #Задаем соответствие между командами, которым нужен оригинальный вывод и функциями-обработчиками
    modified_commands = {
        "system resource print": mod_sys_res_print
    }

    with SSHMikrotik(args.address, port, username, args.password) as mt_ssh:
        try:
            #Если нужен оригинальный вывод, используем функцию-обработчик
            if " ".join(args.command) in modified_commands:
                modified_commands.get(" ".join(args.command))(mt_ssh.execute(args.command))
            else:
                print(mt_ssh.execute(args.command))
        except Exception:
            pass
if __name__ == '__main__':
    main()
