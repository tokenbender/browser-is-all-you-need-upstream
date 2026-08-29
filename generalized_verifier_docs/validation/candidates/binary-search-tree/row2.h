#if !defined(BINARY_SEARCH_TREE_H)
#define BINARY_SEARCH_TREE_H

namespace binary_search_tree {

template <typename T>
class Node {
public:
    T data;
    Node* left;
    Node* right;

    Node(const T& value) : data(value), left(nullptr), right(nullptr) {}
};

template <typename T>
class BinarySearchTree {
public:
    BinarySearchTree() : root_(nullptr) {}
    ~BinarySearchTree();

    void insert(const T& value);
    bool search(const T& value) const;

private:
    Node* root_;

    void insert(Node*& node, const T& value);
    bool search(Node* node, const T& value) const;
};

}  // namespace binary_search_tree

#endif // BINARY_SEARCH_TREE_H
