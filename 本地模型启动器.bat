@echo off
chcp 65001 >nul
color 0A
setlocal

:: ==========================================
:: 全局环境
:: ==========================================

set "LLAMA_DIR=D:\Program files\Llama"
cd /d "%LLAMA_DIR%"

set GGML_CUDA_FORCE_MMQ=1

:: ==========================================
:: 全局端口
:: ==========================================

set "PORT_MAIN=8080"
set "PORT_EMB=8081"
set "PORT_RERANK=8082"

:: ==========================================
:: 全局公共参数
:: ==========================================

set "COMMON=--host 127.0.0.1 --port %PORT_MAIN% -fa on"

:: ==========================================
:: 9B 模型
:: ==========================================

set "MODEL_9B=D:\Program files\Llama\Models\Qwen3.5-9B\Qwen3.5-9B-Q4_K_M.gguf"
set "MM_9B=D:\Program files\Llama\Models\Qwen3.5-9B\mmproj-BF16.gguf"

set "CFG_9B_TEXT=-c 16384 -ngl 99 -ctk q8_0 -ctv q8_0 -b 1024 -ub 512 -np 1 --no-mmap"
set "CFG_9B_AGENT=-c 131072 -ngl 99 -ctk q8_0 -ctv q8_0 -b 1024 -ub 512 -np 1 --no-mmap --cache-ram 1024 --ctx-checkpoints 16 --jinja -n 4096"

:: ==========================================
:: 35B 模型
:: ==========================================

set "MODEL_35B=D:\Program files\Llama\Models\Qwen3.6-35B\Qwen3.6-35B-A3B-APEX-I-Compact.gguf"
set "MM_35B=D:\Program files\Llama\Models\Qwen3.6-35B\mmproj.gguf"

set "CFG_35B_TEXT=-c 16384 -ctk q8_0 -ctv q8_0 -b 1024 -ub 512 -np 1 --no-mmap --mlock"
set "CFG_35B_AGENT=-c 65536 -ctk q8_0 -ctv q8_0 -b 768 -ub 512 -np 1 --no-mmap --mlock --cache-ram 1024 --ctx-checkpoints 16 --jinja -n 4096"

:: ==========================================
:: 4B 模型
:: ==========================================

set "MODEL_4B=D:\Program files\Llama\Models\Qwen3.5-4B\Qwen3.5-4B-Q4_K_M.gguf"
set "MM_4B=D:\Program files\Llama\Models\Qwen3.5-4B\mmproj-BF16.gguf"

set "CFG_4B_TEXT=-c 16384 -ngl 99 -ctk q4_0 -ctv q4_0 -b 2048 -ub 512 --jinja -n 4096"
set "CFG_4B_AGENT=-c 32768 -ngl 99 -ctk q4_0 -ctv q4_0 -b 2048 -ub 512 --cache-ram 1024 --ctx-checkpoints 16 --jinja -n 4096"

:: ==========================================
:: 35B 无审查
:: ==========================================

set "MODEL_35B_UNC=D:\Program files\Llama\Models\Qwen3.6-35B-Uncensored\Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf"
set "MM_35B_UNC=D:\Program files\Llama\Models\Qwen3.6-35B-Uncensored\mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-f16.gguf"

set "CFG_35B_UNC=-c 16384 -ctk q8_0 -ctv q8_0 -b 768 -ub 512 -np 1 --no-mmap --mlock --keep -1 --temp 1.0 --top-k 20 --repeat-penalty 1.12 --presence-penalty 0.15 -n 2048"

:: ==========================================
:: Embedding 模型
:: ==========================================

set "MODEL_EMB=D:\Program files\Llama\Models\bge-large-zh\bge-large-zh-v1.5-f32.gguf"
set "CFG_EMB=--embedding -ngl 99 -c 8192 -b 2048 -ub 512 -np 2"

:: ==========================================
:: Reranker 模型
:: ==========================================

set "MODEL_RERANK=D:\Program files\Llama\Models\bge-reranker\bge-reranker-v2-m3-Q8_0.gguf"
set "CFG_RERANK=--reranking -ngl 99 -c 8192 -b 512 -ub 512 -np 2"


:: ==========================================
:: 主菜单
:: ==========================================

:main_menu
cls

echo ==================================================
echo             本地模型启动器
echo ==================================================
echo.
echo [MMQ优化] GGML_CUDA_FORCE_MMQ=1
echo [工作目录] %cd%
echo.
echo --------------------------------------------------
echo    [1] Qwen3.5-9B
echo    [2] Qwen3.6-35B
echo    [3] Qwen3.5-4B
echo    [4] Qwen3.6-35B-Uncensored
echo    [5] 知识库模型
echo --------------------------------------------------
echo.

set "main_choice="
set /p main_choice="请输入序号（直接回车退出）: "

if "%main_choice%"=="" exit
if "%main_choice%"=="1" goto menu_9b
if "%main_choice%"=="2" goto menu_35b
if "%main_choice%"=="3" goto menu_4b
if "%main_choice%"=="4" goto menu_35b_unc
if "%main_choice%"=="5" goto run_kb

goto main_menu


:: ==========================================
:: 9B 菜单
:: ==========================================

:menu_9b
cls

echo ==================================================
echo                Qwen3.5-9B
echo ==================================================
echo.
echo [1] 基础模式 (默认支持视觉)
echo [2] Agent模式 (默认支持视觉)
echo.

set "sub_choice="
set /p sub_choice="请输入序号（直接回车返回）: "

if "%sub_choice%"=="" goto main_menu
if "%sub_choice%"=="1" goto run_9b_base
if "%sub_choice%"=="2" goto run_9b_agent

goto menu_9b

:run_9b_base
cls
echo 启动 Qwen3.5-9B [基础模式]
.\llama-server.exe -m "%MODEL_9B%" --mmproj "%MM_9B%" --image-min-tokens 1024 %CFG_9B_TEXT% %COMMON% --reasoning on
pause
goto main_menu

:run_9b_agent
cls
echo 启动 Qwen3.5-9B [Agent模式]
.\llama-server.exe -m "%MODEL_9B%" --mmproj "%MM_9B%" --image-min-tokens 1024 %CFG_9B_AGENT% %COMMON% --chat-template --reasoning off
pause
goto main_menu


:: ==========================================
:: 35B 菜单
:: ==========================================

:menu_35b
cls

echo ==================================================
echo                Qwen3.6-35B
echo ==================================================
echo.
echo [1] 基础模式
echo [2] 视觉模式
echo [3] Agent基础模式
echo [4] Agent视觉模式
echo.

set "sub_choice="
set /p sub_choice="请输入序号（直接回车返回）: "

if "%sub_choice%"=="" goto main_menu
if "%sub_choice%"=="1" goto run_35b_text
if "%sub_choice%"=="2" goto run_35b_vision
if "%sub_choice%"=="3" goto run_35b_agent
if "%sub_choice%"=="4" goto run_35b_agent_vision

goto menu_35b

:run_35b_text
cls
echo 启动 Qwen3.6-35B [基础模式]
.\llama-server.exe -m "%MODEL_35B%" %CFG_35B_TEXT% %COMMON% --reasoning on
pause
goto main_menu

:run_35b_vision
cls
echo 启动 Qwen3.6-35B [视觉模式]
.\llama-server.exe -m "%MODEL_35B%" --mmproj "%MM_35B%" --image-min-tokens 1024 %CFG_35B_TEXT% %COMMON% --reasoning on
pause
goto main_menu

:run_35b_agent
cls
echo 启动 Qwen3.6-35B [Agent基础模式]
.\llama-server.exe -m "%MODEL_35B%" %CFG_35B_AGENT% %COMMON% --chat-template --reasoning off
pause
goto main_menu

:run_35b_agent_vision
cls
echo 启动 Qwen3.6-35B [Agent视觉模式]
.\llama-server.exe -m "%MODEL_35B%" --mmproj "%MM_35B%" --image-min-tokens 1024 %CFG_35B_AGENT% %COMMON% --chat-template --reasoning off
pause
goto main_menu


:: ==========================================
:: 4B 菜单
:: ==========================================

:menu_4b
cls

echo ==================================================
echo                Qwen3.5-4B
echo ==================================================
echo.
echo [1] 基础模式 (默认支持视觉)
echo [2] Agent模式 (默认支持视觉)
echo.

set "sub_choice="
set /p sub_choice="请输入序号（直接回车返回）: "

if "%sub_choice%"=="" goto main_menu
if "%sub_choice%"=="1" goto run_4b_base
if "%sub_choice%"=="2" goto run_4b_agent

goto menu_4b

:run_4b_base
cls
echo 启动 Qwen3.5-4B [基础模式]
.\llama-server.exe -m "%MODEL_4B%" --mmproj "%MM_4B%" --image-min-tokens 1024 %CFG_4B_TEXT% %COMMON% --reasoning on
pause
goto main_menu

:run_4b_agent
cls
echo 启动 Qwen3.5-4B [Agent模式]
.\llama-server.exe -m "%MODEL_4B%" --mmproj "%MM_4B%" --image-min-tokens 1024 %CFG_4B_AGENT% %COMMON% --chat --reasoning off
pause
goto main_menu


:: ==========================================
:: 35B 无审查菜单
:: ==========================================

:menu_35b_unc
cls

echo ==================================================
echo            Qwen3.6-35B-Uncensored
echo ==================================================
echo.
echo [1] 基础模式
echo [2] 视觉模式
echo.

set "sub_choice="
set /p sub_choice="请输入序号（直接回车返回）: "

if "%sub_choice%"=="" goto main_menu
if "%sub_choice%"=="1" goto run_35b_unc_text
if "%sub_choice%"=="2" goto run_35b_unc_vision

goto menu_35b_unc

:run_35b_unc_text
cls
echo 启动 Qwen3.6-35B 无审查版 [基础模式]
.\llama-server.exe -m "%MODEL_35B_UNC%" %CFG_35B_UNC% %COMMON% --reasoning on
pause
goto main_menu

:run_35b_unc_vision
cls
echo 启动 Qwen3.6-35B 无审查版 [视觉模式]
.\llama-server.exe -m "%MODEL_35B_UNC%" --mmproj "%MM_35B_UNC%" --image-min-tokens 1024 %CFG_35B_UNC% %COMMON% --reasoning on
pause
goto main_menu


:: ==========================================
:: 知识库模型
:: ==========================================

:run_kb
cls

echo 启动知识库组件...
echo.

echo [1/2] Embedding 模型启动中...
start "Embedding" cmd /k .\llama-server.exe -m "%MODEL_EMB%" %CFG_EMB% --host 127.0.0.1 --port %PORT_EMB%

timeout /t 5 /nobreak >nul

echo [2/2] Reranker 模型启动中...
start "Reranker" cmd /k .\llama-server.exe -m "%MODEL_RERANK%" %CFG_RERANK% --host 127.0.0.1 --port %PORT_RERANK%

echo.
echo 知识库组件已启动，主窗口即将关闭...
timeout /t 2 /nobreak >nul
exit
