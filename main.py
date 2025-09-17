#!/usr/bin/env python3
"""
파일시스템 파일 카운터 애플리케이션
Python 3.12+
"""

import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
import paramiko
from tqdm import tqdm
import argparse
from dataclasses import dataclass


@dataclass
class ConnectionConfig:
    """연결 설정 정보"""
    connection_type: str  # 'local' 또는 'ssh'
    directory: str
    username: Optional[str] = None
    password: Optional[str] = None
    hostname: Optional[str] = None
    port: int = 22


class FileCounter:
    """파일 카운터 클래스"""
    
    def __init__(self, config: ConnectionConfig, extensions: List[str]):
        self.config = config
        self.extensions = [ext.lower() if ext.startswith('.') else f'.{ext.lower()}' 
                          for ext in extensions]
        self.ssh_client = None
        self.sftp_client = None
    
    def connect(self):
        """연결 설정"""
        if self.config.connection_type == 'ssh':
            try:
                self.ssh_client = paramiko.SSHClient()
                self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                self.ssh_client.connect(
                    hostname=self.config.hostname,
                    port=self.config.port,
                    username=self.config.username,
                    password=self.config.password
                )
                self.sftp_client = self.ssh_client.open_sftp()
                print(f"SSH 연결 성공: {self.config.username}@{self.config.hostname}")
            except Exception as e:
                print(f"SSH 연결 실패: {e}")
                sys.exit(1)
        else:
            # 로컬 파일시스템의 경우 디렉터리 존재 확인
            if not os.path.exists(self.config.directory):
                print(f"디렉터리가 존재하지 않습니다: {self.config.directory}")
                sys.exit(1)
    
    def disconnect(self):
        """연결 종료"""
        if self.sftp_client:
            self.sftp_client.close()
        if self.ssh_client:
            self.ssh_client.close()
    
    def _is_target_file(self, filename: str) -> bool:
        """대상 파일 확장자인지 확인"""
        if not self.extensions:  # 확장자 리스트가 비어있으면 모든 파일
            return True
        
        file_ext = Path(filename).suffix.lower()
        return file_ext in self.extensions
    
    def _count_files_local(self, directory: str, progress_bar: tqdm) -> int:
        """로컬 파일시스템에서 파일 카운트"""
        count = 0
        try:
            for root, dirs, files in os.walk(directory):
                # 진행율 업데이트
                progress_bar.set_description(f"검색 중: {os.path.basename(root)}")
                progress_bar.update(1)
                
                for file in files:
                    if self._is_target_file(file):
                        count += 1
                        
        except PermissionError as e:
            print(f"권한 오류: {e}")
        except Exception as e:
            print(f"오류 발생: {e}")
            
        return count
    
    def _count_files_ssh(self, directory: str, progress_bar: tqdm) -> int:
        """SSH/SFTP를 통한 원격 파일시스템에서 파일 카운트"""
        count = 0
        
        def _walk_remote(path: str):
            nonlocal count
            try:
                progress_bar.set_description(f"검색 중: {os.path.basename(path)}")
                progress_bar.update(1)
                
                items = self.sftp_client.listdir_attr(path)
                
                for item in items:
                    item_path = f"{path}/{item.filename}".replace('//', '/')
                    
                    # 디렉터리인 경우 재귀 호출
                    if self.sftp_client.stat(item_path).st_mode & 0o040000:  # 디렉터리 체크
                        _walk_remote(item_path)
                    else:
                        # 파일인 경우 확장자 확인
                        if self._is_target_file(item.filename):
                            count += 1
                            
            except PermissionError as e:
                print(f"권한 오류: {e}")
            except Exception as e:
                print(f"오류 발생 ({path}): {e}")
        
        _walk_remote(directory)
        return count
    
    def count_files(self) -> int:
        """파일 개수 카운트 메인 함수"""
        print(f"파일 검색 시작...")
        print(f"대상 디렉터리: {self.config.directory}")
        print(f"대상 확장자: {', '.join(self.extensions) if self.extensions else '모든 파일'}")
        print(f"연결 타입: {self.config.connection_type}")
        
        # 진행률 표시를 위한 tqdm 설정
        with tqdm(desc="파일 검색 중", unit="dirs", bar_format="{desc}: {n} dirs processed") as progress_bar:
            
            if self.config.connection_type == 'local':
                total_count = self._count_files_local(self.config.directory, progress_bar)
            else:
                total_count = self._count_files_ssh(self.config.directory, progress_bar)
        
        return total_count


def load_config(config_file: str) -> tuple[ConnectionConfig, List[str]]:
    """설정 파일 로드"""
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        
        # 연결 설정
        conn_config = ConnectionConfig(
            connection_type=config_data.get('connection_type', 'local'),
            directory=config_data['directory'],
            username=config_data.get('username'),
            password=config_data.get('password'),
            hostname=config_data.get('hostname'),
            port=config_data.get('port', 22)
        )
        
        # 확장자 리스트
        extensions = config_data.get('extensions', [])
        
        return conn_config, extensions
        
    except FileNotFoundError:
        print(f"설정 파일을 찾을 수 없습니다: {config_file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"설정 파일 JSON 파싱 오류: {e}")
        sys.exit(1)
    except KeyError as e:
        print(f"설정 파일에 필수 키가 없습니다: {e}")
        sys.exit(1)


def create_sample_config():
    """샘플 설정 파일 생성"""
    sample_config = {
        "connection_type": "local",  # "local" 또는 "ssh"
        "directory": "/path/to/search/directory",
        "extensions": [".py", ".txt", ".log", ".json"],
        # SSH 연결용 설정 (connection_type이 "ssh"인 경우)
        "hostname": "example.com",
        "username": "your_username",
        "password": "your_password",
        "port": 22
    }
    
    with open('config_sample.json', 'w', encoding='utf-8') as f:
        json.dump(sample_config, f, indent=2, ensure_ascii=False)
    
    print("샘플 설정 파일 'config_sample.json'이 생성되었습니다.")
    print("이 파일을 'config.json'으로 복사하여 수정해서 사용하세요.")


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
    counter = FileCounter(args.config)
    counter.run()


if __name__ == "__main__":
    main()
