#!/usr/bin/env python3
"""
파일시스템 디렉터리 파일 카운터 애플리케이션
Python 3.12 호환
"""

import os
import json
import sys
import argparse
from pathlib import Path
from typing import List, Dict, Tuple
import paramiko
from tqdm import tqdm
import stat


class FileCounter:
    def __init__(self):
        """파일 카운터 초기화"""
        self.config = None
        self.ssh_client = None
        self.sftp_client = None
        
    def load_config(self, config_file: str) -> None:
        """설정 파일 로드"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            self.validate_config()
        except FileNotFoundError:
            print(f"설정 파일을 찾을 수 없습니다: {config_file}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"설정 파일 JSON 파싱 오류: {e}")
            sys.exit(1)
    
    def validate_config(self) -> None:
        """설정 파일 유효성 검사"""
        if not self.config:
            raise ValueError("설정이 로드되지 않았습니다.")
            
        required_keys = ['connection_type', 'directory', 'extensions']
        for key in required_keys:
            if key not in self.config:
                raise ValueError(f"설정 파일에 필수 키가 없습니다: {key}")
        
        if self.config['connection_type'] not in ['local', 'ssh']:
            raise ValueError("connection_type은 'local' 또는 'ssh'여야 합니다.")
        
        if self.config['connection_type'] == 'ssh':
            ssh_required = ['host', 'username', 'password']
            for key in ssh_required:
                if key not in self.config:
                    raise ValueError(f"SSH 연결을 위한 필수 키가 없습니다: {key}")
    
    def connect_ssh(self) -> None:
        """SSH 연결 설정"""
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            print(f"SSH 서버에 연결 중... {self.config['host']}")
            self.ssh_client.connect(
                hostname=self.config['host'],
                username=self.config['username'],
                password=self.config['password'],
                port=self.config.get('port', 22)
            )
            
            self.sftp_client = self.ssh_client.open_sftp()
            print("SSH 연결 성공!")
            
        except Exception as e:
            print(f"SSH 연결 실패: {e}")
            sys.exit(1)
    
    def disconnect_ssh(self) -> None:
        """SSH 연결 종료"""
        if self.sftp_client:
            self.sftp_client.close()
        if self.ssh_client:
            self.ssh_client.close()
    
    def count_directories_local(self, directory: str) -> int:
        """로컬 디렉터리 개수 카운트 (진행률 표시용)"""
        count = 0
        try:
            for root, dirs, files in os.walk(directory):
                count += 1
        except PermissionError:
            pass
        return count
    
    def count_directories_ssh(self, directory: str) -> int:
        """SSH 디렉터리 개수 카운트 (진행률 표시용)"""
        count = 0
        
        def recursive_count(path):
            nonlocal count
            try:
                count += 1
                for item in self.sftp_client.listdir_attr(path):
                    if stat.S_ISDIR(item.st_mode):
                        item_path = f"{path}/{item.filename}" if path != "/" else f"/{item.filename}"
                        recursive_count(item_path)
            except (PermissionError, FileNotFoundError, OSError):
                pass
        
        recursive_count(directory)
        return count
    
    def count_files_local(self, directory: str, extensions: List[str]) -> Tuple[Dict[str, int], int]:
        """로컬 파일시스템에서 파일 카운트"""
        file_counts = {ext: 0 for ext in extensions}
        total_files = 0
        file_list = []
        
        # 총 디렉터리 수 계산
        total_dirs = self.count_directories_local(directory)
        
        with tqdm(total=total_dirs, desc="디렉터리 스캔 중", unit="dirs") as pbar:
            try:
                for root, dirs, files in os.walk(directory):
                    pbar.update(1)
                    for file in files:
                        file_ext = Path(file).suffix.lower()
                        if file_ext in extensions:
                            file_counts[file_ext] += 1
                            total_files += 1

                            full_path = Path(root)/file
                            file_list.append(str(full_path))
            except PermissionError as e:
                print(f"권한 오류: {e}")
            except Exception as e:
                print(f"오류 발생: {e}")
        
        return file_counts, total_files, file_list
    
    def count_files_ssh(self, directory: str, extensions: List[str]) -> Tuple[Dict[str, int], int]:
        """SSH를 통한 원격 파일시스템에서 파일 카운트"""
        file_counts = {ext: 0 for ext in extensions}
        total_files = 0
        
        # 총 디렉터리 수 계산
        total_dirs = self.count_directories_ssh(directory)
        
        def recursive_search(path, pbar):
            nonlocal file_counts, total_files
            try:
                pbar.update(1)
                for item in self.sftp_client.listdir_attr(path):
                    item_path = f"{path}/{item.filename}" if path != "/" else f"/{item.filename}"
                    
                    if stat.S_ISDIR(item.st_mode):
                        # 디렉터리인 경우 재귀 호출
                        recursive_search(item_path, pbar)
                    else:
                        # 파일인 경우 확장자 확인
                        file_ext = Path(item.filename).suffix.lower()
                        if file_ext in extensions:
                            file_counts[file_ext] += 1
                            total_files += 1
                            
            except (PermissionError, FileNotFoundError, OSError) as e:
                print(f"\n경고: {path} 접근 불가 - {e}")
        
        with tqdm(total=total_dirs, desc="원격 디렉터리 스캔 중", unit="dirs") as pbar:
            recursive_search(directory, pbar)
        
        return file_counts, total_files
    
    def run(self, config_file: str = "config.json") -> None:
        """메인 실행 함수"""
        print("=" * 60)
        print("파일 카운터 애플리케이션 시작")
        print("=" * 60)
        
        # 설정 파일 로드
        self.load_config(config_file)
        
        connection_type = self.config['connection_type']
        directory = self.config['directory']
        extensions = self.config['extensions']
        
        print(f"연결 타입: {connection_type}")
        print(f"대상 디렉터리: {directory}")
        print(f"검색할 확장자: {', '.join(extensions)}")
        print("-" * 60)
        
        try:
            if connection_type == 'ssh':
                self.connect_ssh()
                file_counts, total_files = self.count_files_ssh(directory, extensions)
                self.disconnect_ssh()
            else:
                file_counts, total_files, file_list = self.count_files_local(directory, extensions)
            
            # 결과 출력
            print("\n" + "=" * 60)
            print("파일 카운트 결과")
            print("=" * 60)
            
            for ext, count in file_counts.items():
                print(f"{ext:>15} : {count:>8,}개")
            
            print("-" * 60)
            print(f"{'총 파일 수':>15} : {total_files:>8,}개")
            print("=" * 60)
            print("file_list = ", file_list)
            
        except KeyboardInterrupt:
            print("\n\n프로그램이 사용자에 의해 중단되었습니다.")
        except Exception as e:
            print(f"\n오류 발생: {e}")
        finally:
            if connection_type == 'ssh':
                self.disconnect_ssh()


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description="파일시스템 디렉터리 파일 카운터")
    parser.add_argument(
        '--config', 
        default='config.json',
        help='설정 파일 경로 (기본값: config.json)'
    )
    
    args = parser.parse_args()
    
    # 파일 카운터 실행
    counter = FileCounter()
    counter.run(args.config)


if __name__ == "__main__":
    main()
