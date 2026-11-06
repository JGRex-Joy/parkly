import React, { useState } from "react";
import { StatusBar } from "expo-status-bar";
import { SafeAreaView, StyleSheet } from "react-native";
import ServerSetupScreen, { DisplayMode } from "./src/screens/ServerSetupScreen";
import EntryDisplayScreen from "./src/screens/EntryDisplayScreen";
import ExitDisplayScreen from "./src/screens/ExitDisplayScreen";

export default function App() {
  const [host, setHost] = useState<string | null>(null);
  const [mode, setMode] = useState<DisplayMode | null>(null);

  const handleSelect = (selectedHost: string, selectedMode: DisplayMode) => {
    setHost(selectedHost);
    setMode(selectedMode);
  };

  const handleBack = () => {
    setMode(null);
  };

  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar style="light" />
      {!host || !mode ? (
        <ServerSetupScreen onSelect={handleSelect} />
      ) : mode === "entry" ? (
        <EntryDisplayScreen host={host} onBack={handleBack} />
      ) : (
        <ExitDisplayScreen host={host} onBack={handleBack} />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: "#0f172a" },
});
