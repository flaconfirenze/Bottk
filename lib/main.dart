import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:file_picker/file_picker.dart';
import 'package:path_provider/path_provider.dart';
import 'package:path/path.dart' as p;
import 'package:crypto/crypto.dart';
import 'package:encrypt/encrypt.dart' as enc;

void main() {
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AppCloner Crypto',
      theme: ThemeData(
        primarySwatch: Colors.blue,
        useMaterial3: true,
      ),
      home: const MyHomePage(),
    );
  }
}

class MyHomePage extends StatefulWidget {
  const MyHomePage({super.key});

  @override
  State<MyHomePage> createState() => _MyHomePageState();
}

class _MyHomePageState extends State<MyHomePage> {
  final _packageNameController = TextEditingController();
  final _cloneTimestampController = TextEditingController();
  String? _inputDirectory;
  final _log = <String>[];
  bool _isBusy = false;
  bool _showLog = false;

  // Constants from Python script
  static const String KEY_PREFIX = "584BEF6DF3297F91623E2DE659BF8D2F";
  static const String RESOURCE_PREFIX = "A8F5F167F44F4964E6C998DEE827110C";
  static const int MAX_CHAIN_DEPTH = 50;

  void _logMessage(String message) {
    setState(() {
      _log.add(message);
    });
  }

  Future<void> _pickDirectory() async {
    String? selectedDirectory = await FilePicker.platform.getDirectoryPath();
    if (selectedDirectory != null) {
      setState(() {
        _inputDirectory = selectedDirectory;
      });
      _logMessage("Input directory selected: $selectedDirectory");
    }
  }

  Future<void> _decryptChain() async {
    if (_inputDirectory == null || _packageNameController.text.isEmpty || _cloneTimestampController.text.isEmpty) {
      _logMessage("Please select an input directory and fill in all fields.");
      return;
    }

    setState(() {
      _isBusy = true;
      _log.clear();
    });

    try {
      final properties = await _performDecryption();
      if (properties.isNotEmpty) {
        await _saveDecryptedProperties(properties);
      }
    } catch (e) {
      _logMessage("An error occurred: $e");
    } finally {
      setState(() {
        _isBusy = false;
      });
    }
  }

  Future<Map<String, String>> _performDecryption() async {
    _logMessage("Starting decryption...");
    final combinedProperties = <String, String>{};
    int filesDecryptedCount = 0;
    int currentChainDepth = 0;

    String initialKeySource = KEY_PREFIX + _packageNameController.text + _cloneTimestampController.text;
    String currentKeyMd5 = md5.convert(utf8.encode(initialKeySource)).toString().toUpperCase();
    _logMessage("Initial Key MD5: $currentKeyMd5");

    while (currentChainDepth < MAX_CHAIN_DEPTH) {
      currentChainDepth++;
      _logMessage("\n--- Chain Step $currentChainDepth ---");

      String resourceSource = RESOURCE_PREFIX + currentKeyMd5;
      String currentResourceNameHash = md5.convert(utf8.encode(resourceSource)).toString().toUpperCase();
      _logMessage("Searching for resource file: $currentResourceNameHash");

      final currentFilePath = p.join(_inputDirectory!, currentResourceNameHash);
      final file = File(currentFilePath);

      if (!await file.exists()) {
        _logMessage("Resource file not found. End of chain.");
        break;
      }

      _logMessage("Found file: $currentResourceNameHash");

      final encryptedBytes = await file.readAsBytes();
      if (encryptedBytes.isEmpty) {
        _logMessage("File is empty. Stopping chain.");
        break;
      }
      _logMessage("Read ${encryptedBytes.length} bytes.");

      final key = enc.Key.fromUtf8(currentKeyMd5);
      final encrypter = enc.Encrypter(enc.AES(key, mode: enc.AESMode.ecb, padding: 'PKCS7'));

      try {
        final decryptedBytes = encrypter.decryptBytes(enc.Encrypted(encryptedBytes));
        _logMessage("Decryption successful (${decryptedBytes.length} bytes)");

        final currentProperties = _parseProperties(Uint8List.fromList(decryptedBytes));
        _logMessage("Parsed ${currentProperties.length} properties.");

        combinedProperties.addAll(currentProperties);
        filesDecryptedCount++;

        currentKeyMd5 = currentResourceNameHash;
      } catch (e) {
        _logMessage("Decryption failed for this step. Stopping chain.");
        break;
      }
    }

    if (currentChainDepth >= MAX_CHAIN_DEPTH) {
      _logMessage("\nWarning: Reached maximum chain depth ($MAX_CHAIN_DEPTH). Stopped.");
    }

    _logMessage("\nDecryption summary: $filesDecryptedCount files decrypted.");
    return combinedProperties;
  }

  String _escapeProperty(String s, {bool isKey = false}) {
    final out = StringBuffer();
    for (var i = 0; i < s.length; i++) {
      final char = s[i];
      if (char == '\\') {
        out.write('\\\\');
      } else if (char == '\n') {
        out.write('\\n');
      } else if (char == '\r') {
        out.write('\\r');
      } else if (char == '\t') {
        out.write('\\t');
      } else if (char == '\f') {
        out.write('\\f');
      } else if (char == '=' && isKey) {
        out.write('\\=');
      } else if (char == ':' && isKey) {
        out.write('\\:');
      } else if (char == '#' && isKey) {
        out.write('\\#');
      } else if (char == '!' && isKey) {
        out.write('\\!');
      } else if (char == ' ' && isKey) {
        out.write('\\ ');
      } else if (s.codeUnitAt(i) < 32 || s.codeUnitAt(i) > 126) {
        out.write('\\u${s.codeUnitAt(i).toRadixString(16).padLeft(4, '0')}');
      } else {
        out.write(char);
      }
    }
    return out.toString();
  }

  Future<void> _saveDecryptedProperties(Map<String, String> properties) async {
    final outputDir = Directory(p.join(p.dirname(_inputDirectory!), "decrypted_files_flutter"));
    if (!await outputDir.exists()) {
      await outputDir.create(recursive: true);
    }
    final outputFile = File(p.join(outputDir.path, "combined.decrypted.properties"));

    final buffer = StringBuffer();
    buffer.writeln("# Decrypted Properties - ${DateTime.now()}");
    properties.forEach((key, value) {
      final escapedKey = _escapeProperty(key, isKey: true);
      final escapedValue = _escapeProperty(value);
      buffer.writeln("$escapedKey=$escapedValue");
    });

    await outputFile.writeAsString(buffer.toString());
    _logMessage("Saved decrypted properties to: ${outputFile.path}");
  }

  String _unescapeJavaProperty(String s) {
    final result = StringBuffer();
    var i = 0;
    while (i < s.length) {
      if (s[i] == '\\' && i + 1 < s.length) {
        final nextChar = s[i + 1];
        if (nextChar == 'n') {
          result.write('\n');
          i += 1;
        } else if (nextChar == 'r') {
          result.write('\r');
          i += 1;
        } else if (nextChar == 't') {
          result.write('\t');
          i += 1;
        } else if (nextChar == 'f') {
          result.write('\f');
          i += 1;
        } else if (nextChar == 'u' && i + 5 < s.length) {
          try {
            final unicodeVal = int.parse(s.substring(i + 2, i + 6), radix: 16);
            result.write(String.fromCharCode(unicodeVal));
            i += 5;
          } catch (e) {
            result.write('\\u');
            i += 1;
          }
        } else if (['\\', '=', ':', ' '].contains(nextChar)) {
          result.write(nextChar);
          i += 1;
        } else {
          result.write(nextChar);
          i += 1;
        }
      } else {
        result.write(s[i]);
      }
      i += 1;
    }
    return result.toString();
  }

  Map<String, String> _parseProperties(Uint8List data) {
    String decodedText;
    try {
      decodedText = latin1.decode(data);
    } catch (e) {
      try {
        decodedText = utf8.decode(data);
      } catch (e2) {
        _logMessage("Could not decode properties using common encodings.");
        return {};
      }
    }

    final properties = <String, String>{};
    final lines = decodedText.split('\n');
    var i = 0;
    var currentLine = StringBuffer();

    while (i < lines.length) {
      var line = lines[i].trimRight();
      i++;

      final isContinuation = line.endsWith('\\');
      if (isContinuation) {
        currentLine.write(line.substring(0, line.length - 1));
        continue;
      } else {
        currentLine.write(line);
      }

      final logicalLine = currentLine.toString().trim();
      currentLine.clear();

      if (logicalLine.isEmpty || logicalLine.startsWith('#') || logicalLine.startsWith('!')) {
        continue;
      }

      var separatorIndex = -1;
      var j = 0;
      while (j < logicalLine.length) {
        final char = logicalLine[j];
        if (char == '\\') {
          j++;
        } else if (['=', ':'].contains(char)) {
          separatorIndex = j;
          break;
        }
        j++;
      }

      if (separatorIndex != -1) {
        final key = logicalLine.substring(0, separatorIndex).trim();
        final value = logicalLine.substring(separatorIndex + 1).trim();
        properties[_unescapeJavaProperty(key)] = _unescapeJavaProperty(value);
      } else {
        properties[_unescapeJavaProperty(logicalLine)] = "";
      }
    }
    return properties;
  }

  Future<void> _encryptChain() async {
    if (_inputDirectory == null || _packageNameController.text.isEmpty || _cloneTimestampController.text.isEmpty) {
      _logMessage("Please select an output directory and fill in all fields.");
      return;
    }

    FilePickerResult? result = await FilePicker.platform.pickFiles();
    if (result == null) {
      _logMessage("No properties file selected.");
      return;
    }
    final propertiesFile = File(result.files.single.path!);
    final properties = _parseProperties(await propertiesFile.readAsBytes());

    setState(() {
      _isBusy = true;
      _log.clear();
    });

    try {
      await _performEncryption(properties);
    } catch (e) {
      _logMessage("An error occurred: $e");
    } finally {
      setState(() {
        _isBusy = false;
      });
    }
  }

  Future<void> _performEncryption(Map<String, String> properties) async {
    _logMessage("Starting encryption...");
    final outputDir = Directory(p.join(p.dirname(_inputDirectory!), "encrypted_files_flutter"));
    if (await outputDir.exists()) {
      await outputDir.delete(recursive: true);
    }
    await outputDir.create(recursive: true);

    String initialKeySource = KEY_PREFIX + _packageNameController.text + _cloneTimestampController.text;
    String currentKeyMd5 = md5.convert(utf8.encode(initialKeySource)).toString().toUpperCase();
    _logMessage("Initial Key MD5: $currentKeyMd5");

    final propertiesList = properties.entries.toList();
    int currentChainDepth = 0;
    int propertiesEncryptedCount = 0;

    // Split properties into chunks of 10
    for (var i = 0; i < propertiesList.length; i += 10) {
      currentChainDepth++;
      final chunk = Map.fromEntries(propertiesList.sublist(i, i + 10 > propertiesList.length ? propertiesList.length : i + 10));

      final buffer = StringBuffer();
      chunk.forEach((key, value) {
        final escapedKey = _escapeProperty(key, isKey: true);
        final escapedValue = _escapeProperty(value);
        buffer.writeln("$escapedKey=$escapedValue");
      });
      final propertiesBytes = utf8.encode(buffer.toString());

      final key = enc.Key.fromUtf8(currentKeyMd5);
      final encrypter = enc.Encrypter(enc.AES(key, mode: enc.AESMode.ecb, padding: 'PKCS7'));
      final encryptedBytes = encrypter.encryptBytes(propertiesBytes.toList());

      String resourceSource = RESOURCE_PREFIX + currentKeyMd5;
      String currentResourceNameHash = md5.convert(utf8.encode(resourceSource)).toString().toUpperCase();

      final outputFile = File(p.join(outputDir.path, currentResourceNameHash));
      await outputFile.writeAsBytes(encryptedBytes.bytes);
      _logMessage("Encrypted chunk $currentChainDepth to ${outputFile.path}");

      propertiesEncryptedCount += chunk.length;
      currentKeyMd5 = currentResourceNameHash;
    }

    _logMessage("\nEncryption summary: $propertiesEncryptedCount properties encrypted into $currentChainDepth files.");
  }


  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('AppCloner Crypto'),
      ),
      body: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          children: [
            ElevatedButton(
              onPressed: _isBusy ? null : _pickDirectory,
              child: const Text('Pick Directory (for input or output)'),
            ),
            if (_inputDirectory != null) Text('Selected: $_inputDirectory'),
            TextField(
              controller: _packageNameController,
              decoration: const InputDecoration(labelText: 'Package Name'),
            ),
            TextField(
              controller: _cloneTimestampController,
              decoration: const InputDecoration(labelText: 'Clone Timestamp (long)'),
              keyboardType: TextInputType.number,
            ),
            const SizedBox(height: 20),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceEvenly,
              children: [
                ElevatedButton(
                  onPressed: _isBusy ? null : _decryptChain,
                  child: const Text('Decrypt Chain'),
                ),
                ElevatedButton(
                  onPressed: _isBusy ? null : _encryptChain,
                  child: const Text('Encrypt Chain'),
                ),
              ],
            ),
            if (_isBusy)
              const Padding(
                padding: EdgeInsets.all(16.0),
                child: CircularProgressIndicator(),
              ),
            const SizedBox(height: 20),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text("Live Log"),
                IconButton(
                  icon: Icon(_showLog ? Icons.expand_less : Icons.expand_more),
                  onPressed: () {
                    setState(() {
                      _showLog = !_showLog;
                    });
                  },
                ),
              ],
            ),
            if (_showLog)
              Expanded(
                child: Container(
                  padding: const EdgeInsets.all(8.0),
                  color: Colors.grey[200],
                  child: ListView.builder(
                    itemCount: _log.length,
                    itemBuilder: (context, index) {
                      return Text(_log[index]);
                    },
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
