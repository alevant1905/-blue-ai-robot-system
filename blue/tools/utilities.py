"""
Blue Robot Utility Tools
========================
Quick utility functions: time, date, calculator, system info, conversions.

These tools handle simple queries that don't need external APIs or services.
"""

from __future__ import annotations

import datetime
import json
import math
import os
import platform
import re
import socket
import subprocess
import sys
from typing import Any, Dict, List, Optional, Union


# ================================================================================
# TIME & DATE
# ================================================================================

def get_current_time(timezone: str = None, format_24h: bool = False) -> str:
    """
    Get the current time.

    Args:
        timezone: Optional timezone name (e.g., 'America/Toronto', 'UTC')
        format_24h: Use 24-hour format if True

    Returns:
        JSON string with current time information
    """
    now = datetime.datetime.now()

    # Try to use timezone if specified
    if timezone:
        try:
            import zoneinfo
            tz = zoneinfo.ZoneInfo(timezone)
            now = datetime.datetime.now(tz)
        except Exception:
            pass  # Fall back to local time

    if format_24h:
        time_str = now.strftime("%H:%M:%S")
    else:
        time_str = now.strftime("%I:%M %p").lstrip('0')

    return json.dumps({
        "success": True,
        "time": time_str,
        "time_24h": now.strftime("%H:%M:%S"),
        "hour": now.hour,
        "minute": now.minute,
        "second": now.second,
        "timezone": timezone or "local",
        "iso": now.isoformat()
    })


def get_current_date(format_style: str = "full") -> str:
    """
    Get the current date.

    Args:
        format_style: "full", "short", "iso", or "spoken"

    Returns:
        JSON string with current date information
    """
    now = datetime.datetime.now()

    formats = {
        "full": now.strftime("%A, %B %d, %Y"),
        "short": now.strftime("%m/%d/%Y"),
        "iso": now.strftime("%Y-%m-%d"),
        "spoken": now.strftime("%A, %B %-d" if os.name != 'nt' else "%A, %B %d").replace(" 0", " ")
    }

    return json.dumps({
        "success": True,
        "date": formats.get(format_style, formats["full"]),
        "day_of_week": now.strftime("%A"),
        "day": now.day,
        "month": now.strftime("%B"),
        "month_num": now.month,
        "year": now.year,
        "week_number": now.isocalendar()[1],
        "day_of_year": now.timetuple().tm_yday,
        "iso": now.strftime("%Y-%m-%d")
    })


def get_datetime_info() -> str:
    """Get comprehensive date and time information."""
    now = datetime.datetime.now()

    # Determine time of day
    hour = now.hour
    if 5 <= hour < 12:
        time_of_day = "morning"
    elif 12 <= hour < 17:
        time_of_day = "afternoon"
    elif 17 <= hour < 21:
        time_of_day = "evening"
    else:
        time_of_day = "night"

    # Calculate days until events
    today = now.date()
    year = today.year

    # Next weekend
    days_until_weekend = (5 - today.weekday()) % 7
    if days_until_weekend == 0 and today.weekday() < 5:
        days_until_weekend = 5 - today.weekday()

    # Holidays (simple calculation)
    holidays = {
        "Christmas": datetime.date(year if today < datetime.date(year, 12, 25) else year + 1, 12, 25),
        "New Year": datetime.date(year + 1, 1, 1),
        "Valentine's Day": datetime.date(year if today < datetime.date(year, 2, 14) else year + 1, 2, 14),
    }

    days_until = {}
    for name, date in holidays.items():
        delta = (date - today).days
        if delta > 0:
            days_until[name] = delta

    return json.dumps({
        "success": True,
        "current_time": now.strftime("%I:%M %p").lstrip('0'),
        "current_date": now.strftime("%A, %B %d, %Y"),
        "time_of_day": time_of_day,
        "is_weekend": today.weekday() >= 5,
        "days_until_weekend": days_until_weekend,
        "days_until_holidays": days_until,
        "greeting": f"Good {time_of_day}!"
    })


# ================================================================================
# CALCULATOR
# ================================================================================

def _eval_math_ast(expr: str, safe_dict: Dict[str, Any]) -> Any:
    """Evaluate arithmetic expressions through AST nodes, not eval."""
    import ast
    import operator

    bin_ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    unary_ops = {ast.UAdd: operator.pos, ast.USub: operator.neg}

    def eval_node(node, depth=0):
        if depth > 20:
            raise ValueError("expression is too complex")
        if isinstance(node, ast.Expression):
            return eval_node(node.body, depth + 1)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name) and node.id in safe_dict and not callable(safe_dict[node.id]):
            return safe_dict[node.id]
        if isinstance(node, ast.UnaryOp) and type(node.op) in unary_ops:
            return unary_ops[type(node.op)](eval_node(node.operand, depth + 1))
        if isinstance(node, ast.BinOp) and type(node.op) in bin_ops:
            left = eval_node(node.left, depth + 1)
            right = eval_node(node.right, depth + 1)
            if isinstance(node.op, ast.Pow) and abs(right) > 12:
                raise ValueError("exponent is too large")
            result = bin_ops[type(node.op)](left, right)
            if isinstance(result, (int, float)) and abs(result) > 1e18:
                raise ValueError("result is too large")
            return result
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = safe_dict.get(node.func.id)
            if not callable(fn):
                raise ValueError(f"function not allowed: {node.func.id}")
            if len(node.args) > 3 or node.keywords:
                raise ValueError("unsupported function arguments")
            return fn(*[eval_node(arg, depth + 1) for arg in node.args])
        raise ValueError("only arithmetic expressions are allowed")

    return eval_node(ast.parse(expr, mode="eval"))


def calculate(expression: str) -> str:
    """
    Safely evaluate a mathematical expression.

    Args:
        expression: Math expression to evaluate (e.g., "2 + 2", "sqrt(16)", "15% of 200")

    Returns:
        JSON string with result
    """
    try:
        # Clean up the expression
        expr = expression.lower().strip()

        # Handle percentage calculations
        # "15% of 200" -> 200 * 0.15
        percent_match = re.match(r'(\d+(?:\.\d+)?)\s*%\s*of\s*(\d+(?:\.\d+)?)', expr)
        if percent_match:
            percent = float(percent_match.group(1))
            value = float(percent_match.group(2))
            result = value * (percent / 100)
            return json.dumps({
                "success": True,
                "expression": expression,
                "result": result,
                "formatted": f"{percent}% of {value} = {result}"
            })

        # Handle "X percent" -> X/100
        expr = re.sub(r'(\d+(?:\.\d+)?)\s*percent', r'(\1/100)', expr)

        # Handle word operators
        replacements = {
            ' plus ': '+',
            ' minus ': '-',
            ' times ': '*',
            ' multiplied by ': '*',
            ' divided by ': '/',
            ' over ': '/',
            ' to the power of ': '**',
            ' squared': '**2',
            ' cubed': '**3',
            'square root of ': 'sqrt(',
            'sqrt of ': 'sqrt(',
            'pi': str(math.pi),
            'e': str(math.e),
        }

        for word, symbol in replacements.items():
            expr = expr.replace(word, symbol)

        # Close sqrt parentheses if needed
        if 'sqrt(' in expr and expr.count('(') > expr.count(')'):
            expr += ')'

        # Safe math functions
        safe_dict = {
            'sqrt': math.sqrt,
            'sin': math.sin,
            'cos': math.cos,
            'tan': math.tan,
            'log': math.log10,
            'ln': math.log,
            'exp': math.exp,
            'abs': abs,
            'round': round,
            'floor': math.floor,
            'ceil': math.ceil,
            'pow': pow,
            'pi': math.pi,
            'e': math.e,
        }

        # Only allow safe characters
        allowed_chars = set('0123456789+-*/.()^ ')
        expr_check = expr
        for func in safe_dict:
            expr_check = expr_check.replace(func, '')

        if not all(c in allowed_chars for c in expr_check):
            return json.dumps({
                "success": False,
                "error": "Invalid characters in expression",
                "expression": expression
            })

        # Replace ^ with **
        expr = expr.replace('^', '**')

        # Evaluate without executing Python code
        result = _eval_math_ast(expr, safe_dict)

        # Format result
        if isinstance(result, float):
            if result == int(result):
                result = int(result)
            else:
                result = round(result, 10)

        return json.dumps({
            "success": True,
            "expression": expression,
            "result": result,
            "formatted": f"{expression} = {result}"
        })

    except ZeroDivisionError:
        return json.dumps({
            "success": False,
            "error": "Division by zero",
            "expression": expression
        })
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Could not calculate: {str(e)}",
            "expression": expression
        })


# ================================================================================
# UNIT CONVERSIONS
# ================================================================================

def convert_units(value: float, from_unit: str, to_unit: str) -> str:
    """
    Convert between common units.

    Args:
        value: The value to convert
        from_unit: Source unit
        to_unit: Target unit

    Returns:
        JSON string with converted value
    """
    # Normalize unit names
    from_unit = from_unit.lower().strip()
    to_unit = to_unit.lower().strip()

    # Unit aliases
    aliases = {
        'c': 'celsius', 'f': 'fahrenheit', 'k': 'kelvin',
        'km': 'kilometers', 'mi': 'miles', 'm': 'meters', 'ft': 'feet',
        'kg': 'kilograms', 'lb': 'pounds', 'lbs': 'pounds', 'g': 'grams', 'oz': 'ounces',
        'l': 'liters', 'gal': 'gallons', 'ml': 'milliliters',
        'in': 'inches', 'cm': 'centimeters', 'mm': 'millimeters',
    }

    from_unit = aliases.get(from_unit, from_unit)
    to_unit = aliases.get(to_unit, to_unit)

    # Temperature conversions
    if from_unit == 'celsius' and to_unit == 'fahrenheit':
        result = (value * 9/5) + 32
    elif from_unit == 'fahrenheit' and to_unit == 'celsius':
        result = (value - 32) * 5/9
    elif from_unit == 'celsius' and to_unit == 'kelvin':
        result = value + 273.15
    elif from_unit == 'kelvin' and to_unit == 'celsius':
        result = value - 273.15
    elif from_unit == 'fahrenheit' and to_unit == 'kelvin':
        result = (value - 32) * 5/9 + 273.15
    elif from_unit == 'kelvin' and to_unit == 'fahrenheit':
        result = (value - 273.15) * 9/5 + 32

    # Length conversions (base: meters)
    elif from_unit in ['meters', 'kilometers', 'miles', 'feet', 'inches', 'centimeters', 'millimeters', 'yards']:
        to_meters = {
            'meters': 1, 'kilometers': 1000, 'miles': 1609.34, 'feet': 0.3048,
            'inches': 0.0254, 'centimeters': 0.01, 'millimeters': 0.001, 'yards': 0.9144
        }
        from_meters = {k: 1/v for k, v in to_meters.items()}

        if from_unit in to_meters and to_unit in from_meters:
            result = value * to_meters[from_unit] * from_meters[to_unit]
        else:
            return json.dumps({"success": False, "error": f"Unknown unit: {to_unit}"})

    # Weight conversions (base: kilograms)
    elif from_unit in ['kilograms', 'pounds', 'grams', 'ounces', 'stones']:
        to_kg = {
            'kilograms': 1, 'pounds': 0.453592, 'grams': 0.001,
            'ounces': 0.0283495, 'stones': 6.35029
        }
        from_kg = {k: 1/v for k, v in to_kg.items()}

        if from_unit in to_kg and to_unit in from_kg:
            result = value * to_kg[from_unit] * from_kg[to_unit]
        else:
            return json.dumps({"success": False, "error": f"Unknown unit: {to_unit}"})

    # Volume conversions (base: liters)
    elif from_unit in ['liters', 'gallons', 'milliliters', 'cups', 'pints', 'quarts']:
        to_liters = {
            'liters': 1, 'gallons': 3.78541, 'milliliters': 0.001,
            'cups': 0.236588, 'pints': 0.473176, 'quarts': 0.946353
        }
        from_liters = {k: 1/v for k, v in to_liters.items()}

        if from_unit in to_liters and to_unit in from_liters:
            result = value * to_liters[from_unit] * from_liters[to_unit]
        else:
            return json.dumps({"success": False, "error": f"Unknown unit: {to_unit}"})

    else:
        return json.dumps({
            "success": False,
            "error": f"Unknown conversion: {from_unit} to {to_unit}"
        })

    # Format result
    if isinstance(result, float):
        result = round(result, 4)

    return json.dumps({
        "success": True,
        "value": value,
        "from_unit": from_unit,
        "to_unit": to_unit,
        "result": result,
        "formatted": f"{value} {from_unit} = {result} {to_unit}"
    })


# ================================================================================
# SYSTEM INFO
# ================================================================================

def get_system_info() -> str:
    """Get basic system information."""
    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
    except Exception:
        hostname = "unknown"
        ip = "unknown"

    return json.dumps({
        "success": True,
        "platform": platform.system(),
        "platform_version": platform.version(),
        "python_version": sys.version.split()[0],
        "hostname": hostname,
        "local_ip": ip,
        "processor": platform.processor() or "unknown",
        "architecture": platform.machine()
    })


# ================================================================================
# TEXT UTILITIES
# ================================================================================

def count_text(text: str) -> str:
    """
    Count characters, words, sentences, and paragraphs in text.

    Args:
        text: Text to analyze

    Returns:
        JSON string with counts
    """
    # Character counts
    chars_total = len(text)
    chars_no_spaces = len(text.replace(' ', '').replace('\n', '').replace('\t', ''))

    # Word count
    words = text.split()
    word_count = len(words)

    # Sentence count (approximate)
    sentences = re.split(r'[.!?]+', text)
    sentence_count = len([s for s in sentences if s.strip()])

    # Paragraph count
    paragraphs = text.split('\n\n')
    paragraph_count = len([p for p in paragraphs if p.strip()])

    # Reading time (avg 200 words per minute)
    reading_time_minutes = word_count / 200

    return json.dumps({
        "success": True,
        "characters": chars_total,
        "characters_no_spaces": chars_no_spaces,
        "words": word_count,
        "sentences": sentence_count,
        "paragraphs": max(1, paragraph_count),
        "reading_time_minutes": round(reading_time_minutes, 1),
        "average_word_length": round(chars_no_spaces / max(1, word_count), 1)
    })


def generate_random(type: str = "number", min_val: int = 1, max_val: int = 100,
                   length: int = 8, sides: int = 6) -> str:
    """
    Generate random values.

    Args:
        type: "number", "password", "uuid", "coin", "dice"
        min_val: Minimum value for numbers
        max_val: Maximum value for numbers
        length: Length for passwords
        sides: Number of sides for dice (default 6)

    Returns:
        JSON string with generated value
    """
    import random
    import string
    import uuid as uuid_module

    if type == "number":
        result = random.randint(min_val, max_val)
        return json.dumps({
            "success": True,
            "type": "number",
            "result": result,
            "range": f"{min_val}-{max_val}"
        })

    elif type == "password":
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        result = ''.join(random.choice(chars) for _ in range(length))
        return json.dumps({
            "success": True,
            "type": "password",
            "result": result,
            "length": length
        })

    elif type == "uuid":
        result = str(uuid_module.uuid4())
        return json.dumps({
            "success": True,
            "type": "uuid",
            "result": result
        })

    elif type == "coin":
        result = random.choice(["heads", "tails"])
        return json.dumps({
            "success": True,
            "type": "coin_flip",
            "result": result
        })

    elif type == "dice":
        result = random.randint(1, sides)
        return json.dumps({
            "success": True,
            "type": "dice_roll",
            "result": result,
            "sides": sides,
            "notation": f"d{sides}"
        })

    else:
        return json.dumps({
            "success": False,
            "error": f"Unknown random type: {type}"
        })


# ================================================================================
# QUICK EXECUTOR
# ================================================================================

def execute_utility(action: str, params: Dict[str, Any] = None) -> str:
    """
    Execute a utility function based on action type.

    Args:
        action: The utility action to perform
        params: Parameters for the action

    Returns:
        JSON string with result
    """
    if params is None:
        params = {}

    action_lower = action.lower().strip()

    # Time actions
    if action_lower in ['time', 'current_time', 'what_time']:
        return get_current_time(**params)

    # Date actions
    elif action_lower in ['date', 'current_date', 'what_date', 'today']:
        return get_current_date(**params)

    # Date and time
    elif action_lower in ['datetime', 'now', 'date_time']:
        return get_datetime_info()

    # Calculator
    elif action_lower in ['calculate', 'calc', 'math']:
        expression = params.get('expression', params.get('expr', ''))
        return calculate(expression)

    # Unit conversion
    elif action_lower in ['convert', 'conversion']:
        return convert_units(
            params.get('value', 0),
            params.get('from', params.get('from_unit', '')),
            params.get('to', params.get('to_unit', ''))
        )

    # System info
    elif action_lower in ['system', 'system_info', 'sysinfo']:
        return get_system_info()

    # Text counting
    elif action_lower in ['count', 'count_text', 'word_count']:
        return count_text(params.get('text', ''))

    # Random generation
    elif action_lower in ['random', 'generate']:
        return generate_random(**params)

    else:
        return json.dumps({
            "success": False,
            "error": f"Unknown utility action: {action}",
            "available_actions": [
                "time", "date", "datetime", "calculate", "convert",
                "system", "count", "random"
            ]
        })


__all__ = [
    'get_current_time',
    'get_current_date',
    'get_datetime_info',
    'calculate',
    'convert_units',
    'get_system_info',
    'count_text',
    'generate_random',
    'execute_utility',
]
