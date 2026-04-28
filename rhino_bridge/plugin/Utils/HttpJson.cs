using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Net;
using System.Reflection;
using System.Text;

namespace RhinoPrefabGeometryPlugin.Utils;

public static class HttpJson
{
    public static void Write(HttpListenerResponse response, int statusCode, object payload)
    {
        response.StatusCode = statusCode;
        response.ContentType = "application/json; charset=utf-8";
        var json = Serialize(payload);
        var bytes = Encoding.UTF8.GetBytes(json);
        response.ContentLength64 = bytes.Length;
        response.OutputStream.Write(bytes, 0, bytes.Length);
    }

    public static object Error(string message, string code = "internal_error")
    {
        return new Dictionary<string, string>
        {
            ["error"] = message,
            ["code"] = code
        };
    }

    // Small JSON serializer to avoid runtime dependency on System.Web.Extensions.
    private static string Serialize(object? value)
    {
        if (value is null)
        {
            return "null";
        }
        if (value is string s)
        {
            return Quote(s);
        }
        if (value is bool b)
        {
            return b ? "true" : "false";
        }
        if (value is byte or sbyte or short or ushort or int or uint or long or ulong or float or double or decimal)
        {
            return Convert.ToString(value, CultureInfo.InvariantCulture) ?? "0";
        }
        if (value is Enum enumValue)
        {
            return Quote(enumValue.ToString());
        }
        if (value is IDictionary<string, string> mapString)
        {
            return SerializeDictionary(mapString.ToDictionary(item => item.Key, item => (object?)item.Value));
        }
        if (value is IDictionary<string, object> mapObject)
        {
            return SerializeDictionary(mapObject.ToDictionary(item => item.Key, item => (object?)item.Value));
        }
        if (value is IEnumerable<object> list)
        {
            return SerializeArray(list);
        }
        if (value is System.Collections.IEnumerable enumerable && value is not string)
        {
            var items = new List<object?>();
            foreach (var item in enumerable)
            {
                items.Add(item);
            }
            return SerializeArray(items);
        }
        if (IsSerializableObject(value.GetType()))
        {
            return SerializeObject(value);
        }
        return Quote(Convert.ToString(value, CultureInfo.InvariantCulture) ?? string.Empty);
    }

    private static string SerializeDictionary(IDictionary<string, object?> map)
    {
        var parts = map.Select(entry => $"{Quote(entry.Key)}:{Serialize(entry.Value)}");
        return "{" + string.Join(",", parts) + "}";
    }

    private static string SerializeArray(IEnumerable<object?> values)
    {
        var parts = values.Select(Serialize);
        return "[" + string.Join(",", parts) + "]";
    }

    private static string SerializeObject(object value)
    {
        var map = new Dictionary<string, object?>();
        var props = value.GetType().GetProperties(BindingFlags.Instance | BindingFlags.Public);
        foreach (var prop in props)
        {
            if (!prop.CanRead || prop.GetIndexParameters().Length > 0)
            {
                continue;
            }
            map[ToSnakeCase(prop.Name)] = prop.GetValue(value, null);
        }
        return SerializeDictionary(map);
    }

    private static bool IsSerializableObject(Type type)
    {
        if (type == typeof(string))
        {
            return false;
        }
        if (type.IsPrimitive || type.IsEnum)
        {
            return false;
        }
        if (typeof(System.Collections.IEnumerable).IsAssignableFrom(type))
        {
            return false;
        }
        return true;
    }

    private static string ToSnakeCase(string value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return value;
        }
        var chars = new List<char>(value.Length + 4);
        for (var i = 0; i < value.Length; i++)
        {
            var ch = value[i];
            var isUpper = char.IsUpper(ch);
            if (isUpper && i > 0 && (char.IsLower(value[i - 1]) || (i + 1 < value.Length && char.IsLower(value[i + 1]))))
            {
                chars.Add('_');
            }
            chars.Add(char.ToLowerInvariant(ch));
        }
        return new string(chars.ToArray());
    }

    private static string Quote(string value)
    {
        var escaped = value
            .Replace("\\", "\\\\")
            .Replace("\"", "\\\"")
            .Replace("\r", "\\r")
            .Replace("\n", "\\n")
            .Replace("\t", "\\t");
        return "\"" + escaped + "\"";
    }
}

