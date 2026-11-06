import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

const STORAGE_KEY = "smart_parking_server_host";
const DEFAULT_HOST = "192.168.1.50:8000";

export type DisplayMode = "entry" | "exit";

interface Props {
  onSelect: (host: string, mode: DisplayMode) => void;
}

export default function ServerSetupScreen({ onSelect }: Props) {
  const [host, setHost] = useState(DEFAULT_HOST);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY).then((saved) => {
      if (saved) setHost(saved);
      setLoaded(true);
    });
  }, []);

  const handleSelect = async (mode: DisplayMode) => {
    const cleanHost = host.trim().replace(/^https?:\/\//, "").replace(/\/$/, "");
    if (!cleanHost) return;
    await AsyncStorage.setItem(STORAGE_KEY, cleanHost);
    onSelect(cleanHost, mode);
  };

  if (!loaded) return null;

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <Text style={styles.title}>Smart Parking</Text>
      <Text style={styles.subtitle}>Настройка мок-экрана</Text>

      <Text style={styles.label}>Адрес сервера (IP:порт)</Text>
      <TextInput
        style={styles.input}
        value={host}
        onChangeText={setHost}
        placeholder="192.168.1.50:8000"
        placeholderTextColor="#64748b"
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
      />
      <Text style={styles.hint}>
        Тот же IP, с которым запущен uvicorn (PARKING_BASE_URL на бэкенде должен совпадать).
      </Text>

      <View style={styles.buttonsRow}>
        <TouchableOpacity
          style={[styles.modeButton, styles.entryButton]}
          onPress={() => handleSelect("entry")}
        >
          <Text style={styles.modeButtonTitle}>Экран ВЪЕЗДА</Text>
          <Text style={styles.modeButtonSubtitle}>Свободные места + тариф</Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.modeButton, styles.exitButton]}
          onPress={() => handleSelect("exit")}
        >
          <Text style={styles.modeButtonTitle}>🅿Экран ВЫЕЗДА</Text>
          <Text style={styles.modeButtonSubtitle}>QR, время, сумма</Text>
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#0f172a",
    padding: 24,
    justifyContent: "center",
  },
  title: { color: "#fff", fontSize: 32, fontWeight: "800", textAlign: "center" },
  subtitle: { color: "#94a3b8", fontSize: 15, textAlign: "center", marginBottom: 32 },
  label: { color: "#cbd5e1", fontSize: 14, fontWeight: "600", marginBottom: 8 },
  input: {
    backgroundColor: "#1e293b",
    color: "#fff",
    fontSize: 16,
    padding: 14,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#334155",
  },
  hint: { color: "#64748b", fontSize: 12, marginTop: 8, marginBottom: 32 },
  buttonsRow: { flexDirection: "row", gap: 12 },
  modeButton: {
    flex: 1,
    borderRadius: 14,
    padding: 20,
    alignItems: "center",
  },
  entryButton: { backgroundColor: "#1d4ed8" },
  exitButton: { backgroundColor: "#7c3aed" },
  modeButtonTitle: { color: "#fff", fontSize: 17, fontWeight: "700", marginBottom: 4 },
  modeButtonSubtitle: { color: "rgba(255,255,255,0.75)", fontSize: 12 },
});
