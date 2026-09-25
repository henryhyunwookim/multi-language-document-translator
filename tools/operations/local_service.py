"""
Own a Windows service process tree and terminate its descendants on launcher exit.

Usage: python local_service.py <launcher-pid> <executable> [arguments...]
Prerequisites: Windows, Python 3.10+, and kernel32 Job Object support.
Inputs: the launcher PID and the exact service command.
Output: the child service exit code; no files are written.
"""
import ctypes
from ctypes import wintypes
import subprocess
import sys


def main() -> int:
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]

    class BasicLimits(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                    ('flags', wintypes.DWORD), ('min_working', ctypes.c_size_t),
                    ('max_working', ctypes.c_size_t), ('active', wintypes.DWORD),
                    ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                    ('scheduling', wintypes.DWORD)]

    class Limits(ctypes.Structure):
        _fields_ = [('basic', BasicLimits), ('io', ctypes.c_uint64 * 6),
                    ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                    ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]

    parent = kernel.OpenProcess(0x100000, False, int(sys.argv[1]))
    job = kernel.CreateJobObjectW(None, None)
    child = None
    try:
        if not parent or not job:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Limits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        # Suspend before assignment so descendants cannot escape the job.
        child = subprocess.Popen(sys.argv[2:], creationflags=0x4 | subprocess.CREATE_NO_WINDOW)
        if not kernel.AssignProcessToJobObject(job, int(child._handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        ntdll = ctypes.WinDLL('ntdll')
        ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
        ntdll.NtResumeProcess.restype = wintypes.LONG
        if ntdll.NtResumeProcess(int(child._handle)) != 0:
            raise RuntimeError('Could not resume local service')
        while child.poll() is None:
            status = kernel.WaitForSingleObject(parent, 250)
            if status == 0:
                return 0
            if status != 258:  # WAIT_TIMEOUT
                raise ctypes.WinError(ctypes.get_last_error())
        return child.returncode
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
        if job:
            kernel.CloseHandle(job)
        if parent:
            kernel.CloseHandle(parent)
        if child is not None:
            child.wait()


if __name__ == '__main__':
    sys.exit(main())
