@echo off
REM PDF去水印工具 - 依赖安装脚本

echo 正在安装PDF去水印工具依赖...
echo.

REM 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到Python，请先安装Python 3.8+
    pause
    exit /b 1
)

REM 安装依赖
echo 正在安装PyMuPDF...
pip install PyMuPDF

echo.
echo 正在安装pdfminer.six...
pip install pdfminer.six

echo.
echo 正在安装Pillow...
pip install Pillow

echo.
echo 安装完成！
echo.
echo 使用方法:
echo   python pdf_watermark_removal.py input.pdf
echo   python pdf_watermark_removal.py input.pdf -o output.pdf
echo.

pause
