import React from "react";
import { View, Text, StyleSheet } from "react-native";
import type { ConnectionStatus } from "../hooks/useWebSocket";

const LABELS: Record<ConnectionStatus, string> = {
  connected: "Онлайн",
  connecting: "Подключение…",
  disconnected: "Нет связи с сервером",
};

const COLORS: Record<ConnectionStatus, string> = {
  connected: "#22c55e",
  connecting: "#f59e0b",
  disconnected: "#ef4444",
};

export default function ConnectionBadge({ status }: { status: ConnectionStatus }) {
  return (
    <View style={styles.container}>
      <View style={[styles.dot, { backgroundColor: COLORS[status] }]} />
      <Text style={styles.text}>{LABELS[status]}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    backgroundColor: "rgba(255,255,255,0.06)",
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 20,
  },
  dot: { width: 8, height: 8, borderRadius: 4, marginRight: 8 },
  text: { color: "#cbd5e1", fontSize: 13, fontWeight: "600" },
});
